#!/usr/bin/env python3
"""
RockTimer Central Server
Runs on the Pi 4 at the near hog line.
Collects timestamps, calculates times, and serves the web UI.
"""

import asyncio
import socket
import json
import time
import os
import yaml
import logging
import threading
import subprocess
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager
from enum import Enum
from dataclasses import dataclass

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, Response
import uvicorn

# Try importing gpiozero
try:
    from gpiozero import Button
    from gpiozero.pins.lgpio import LGPIOFactory
    from gpiozero import Device
    Device.pin_factory = LGPIOFactory()
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("WARNING: gpiozero not available, running in simulation mode")

# Config path
CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"
RUNTIME_SETTINGS_PATH = Path(__file__).parent.parent / "runtime_settings.json"

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('rocktimer-server')


class SystemState(str, Enum):
    IDLE = "idle"
    ARMED = "armed"
    MEASURING = "measuring"
    COMPLETED = "completed"


@dataclass
class TimingRecord:
    id: int
    timestamp: datetime
    tee_to_hog_close_ms: float
    hog_to_hog_ms: Optional[float]  # None if the stone did not reach hog_far
    total_ms: Optional[float]


class TimingSession:
    """Holds state for a measurement session."""
    
    def __init__(self):
        self.reset()
    
    def reset(self):
        self.tee_time_ns: Optional[int] = None
        self.hog_close_time_ns: Optional[int] = None
        self.hog_far_time_ns: Optional[int] = None
        self.started_at: Optional[datetime] = None
    
    @property
    def tee_to_hog_close_ms(self) -> Optional[float]:
        if self.tee_time_ns and self.hog_close_time_ns:
            return (self.hog_close_time_ns - self.tee_time_ns) / 1_000_000
        return None
    
    @property
    def hog_to_hog_ms(self) -> Optional[float]:
        if self.hog_close_time_ns and self.hog_far_time_ns:
            return (self.hog_far_time_ns - self.hog_close_time_ns) / 1_000_000
        return None
    
    @property
    def total_ms(self) -> Optional[float]:
        if self.tee_time_ns and self.hog_far_time_ns:
            return (self.hog_far_time_ns - self.tee_time_ns) / 1_000_000
        return None
    
    @property
    def has_hog_close(self) -> bool:
        """True if the stone passed the near hog line."""
        return self.tee_time_ns is not None and self.hog_close_time_ns is not None
    
    @property
    def has_hog_far(self) -> bool:
        """True om stenen passerat andra hog-linjen."""
        return self.hog_far_time_ns is not None
    
    def to_dict(self) -> dict:
        return {
            'tee_time_ns': self.tee_time_ns,
            'hog_close_time_ns': self.hog_close_time_ns,
            'hog_far_time_ns': self.hog_far_time_ns,
            'tee_to_hog_close_ms': self.tee_to_hog_close_ms,
            'hog_to_hog_ms': self.hog_to_hog_ms,
            'total_ms': self.total_ms,
            'has_hog_close': self.has_hog_close,
            'has_hog_far': self.has_hog_far,
            'started_at': self.started_at.isoformat() if self.started_at else None
        }


class RockTimerServer:
    """Main class for the RockTimer server.
    
    Responsibilities:
    - Listen for UDP triggers from remote sensors (Pi Zero units)
    - Handle local GPIO sensor (hog_close timing sensor on Pi 4)
    - Manage system state (idle, armed, measuring, completed)
    - Calculate split times between trigger points
    - Broadcast state updates to WebSocket clients
    - Optional: speak times via TTS
    - Maintain measurement history
    
    State machine:
        IDLE → ARMED (via arm button or IR sensor)
        ARMED → MEASURING (on first trigger)
        MEASURING → COMPLETED (on hog_close trigger)
        COMPLETED → ARMED (via rearm/arm)
        COMPLETED → IDLE (via disarm)
    """
    
    def __init__(self, config_path: Path = CONFIG_PATH):
        self.config = self._load_config(config_path)
        self.state = SystemState.IDLE
        self.session = TimingSession()
        self.websocket_clients: list[WebSocket] = []
        self._loop = None  # Event loop reference, set when the server starts

        # Sensor liveness tracking (remote sensors send periodic heartbeats).
        # Map: device_id -> { last_seen_ts: float, addr: (ip, port), source: str }
        self.sensor_last_seen: dict[str, dict] = {}
        self.sensor_timeout_s: float = float(self.config.get('server', {}).get('sensor_timeout_s', 12.0))
        
        # Speech settings (runtime). Defaults come from config, but can be changed via /api/settings.
        speech_cfg = self.config.get('server', {}).get('speech', {}) or {}
        self.speech_settings = {
            'speech_enabled': self.config['server'].get('enable_speech', False),
            'speak_tee_hog': bool(speech_cfg.get('speak_tee_hog', True)),
            'speak_hog_hog': bool(speech_cfg.get('speak_hog_hog', False)),
            'speak_ready': bool(speech_cfg.get('speak_ready', True)),
        }

        # Auto-rearm settings (runtime). Used to recover if we get stuck in MEASURING.
        auto_rearm_cfg = self.config.get('server', {}).get('auto_rearm', {}) or {}
        self.speech_settings.update({
            # If enabled: after first trigger moves ARMED -> MEASURING, auto-arm back to ARMED
            # after N seconds, but only if we are still in MEASURING.
            'auto_rearm_enabled': bool(auto_rearm_cfg.get('enabled', False)),
            'auto_rearm_after_s': int(auto_rearm_cfg.get('after_s', 120)),
        })
        self._measurement_token: int = 0
        self._auto_rearm_future = None  # concurrent.futures.Future from run_coroutine_threadsafe

        # Persisted runtime settings override (survives restarts even if config.yaml isn't edited).
        self._load_runtime_settings()
        
        # In-memory history
        self.history: list[TimingRecord] = []
        self._next_id = 1
        
        # UDP socket to receive triggers
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp_socket.bind(('0.0.0.0', self.config['server']['udp_port']))
        
        self._udp_thread = None
        self._running = False
        
        logger.info(f"RockTimer Server - UDP port {self.config['server']['udp_port']}")

    def _tts_env(self) -> dict:
        """Environment variables for TTS subprocesses.

        If you use the Pi 4 analog jack (bcm2835 Headphones), you typically want:
        ALSA_DEVICE=hw:0,0
        """
        env = dict(os.environ)
        env.setdefault('HOME', '/root')
        # systemd units often set a very minimal PATH; make sure common tools exist for speak.sh
        env['PATH'] = env.get('PATH', '')
        if env['PATH'].strip() == '' or env['PATH'] == self.config.get('server', {}).get('venv_path_only'):
            pass
        if '/usr/bin' not in env['PATH']:
            env['PATH'] = f"/usr/bin:{env['PATH']}"
        if '/bin' not in env['PATH']:
            env['PATH'] = f"/bin:{env['PATH']}"
        alsa_device = self.config.get('server', {}).get('alsa_device')
        if alsa_device:
            env['ALSA_DEVICE'] = str(alsa_device)
        # Optional: only set ALSA_CARD if explicitly configured.
        alsa_card = self.config.get('server', {}).get('alsa_card')
        if alsa_card is not None:
            env['ALSA_CARD'] = str(alsa_card)
        return env

    def _tts_debug_log_path(self) -> str:
        return self.config.get('server', {}).get('tts_debug_log', '/var/log/rocktimer-tts-spawn.log')

    def _spawn_tts(self, text: str) -> None:
        """Spawn the TTS helper script and log spawn details for troubleshooting."""
        speak_script = '/opt/piper/speak.sh'
        if not os.path.exists(speak_script):
            raise FileNotFoundError(speak_script)

        env = self._tts_env()
        debug_log = self._tts_debug_log_path()
        # Ensure we always capture something when troubleshooting.
        with open(debug_log, 'a') as f:
            f.write(f"{datetime.now().isoformat()} spawn speak.sh text={text!r} "
                    f"ALSA_DEVICE={env.get('ALSA_DEVICE')!r} ALSA_CARD={env.get('ALSA_CARD')!r}\n")
            f.flush()

            # Send speak.sh stdout/stderr to the same file to catch ALSA/aplay errors.
            subprocess.Popen(
                [speak_script, text],
                stdout=f,
                stderr=f,
                env=env,
                start_new_session=True
            )
    
    def _load_config(self, config_path: Path) -> dict:
        if not config_path.exists():
            raise FileNotFoundError(f"Config file missing: {config_path}")
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    
    def setup_gpio(self):
        """Configure GPIO for local sensors."""
        if not GPIO_AVAILABLE:
            logger.warning("GPIO not available - running without local sensors")
            return
        
        try:
            # Hog close sensor (tidtagning)
            sensor_pin = self.config['gpio']['sensor_pin']
            debounce_s = self.config['gpio']['debounce_ms'] / 1000.0
            
            self.sensor_button = Button(
                sensor_pin, 
                pull_up=True, 
                bounce_time=debounce_s
            )
            self.sensor_button.when_pressed = self._local_sensor_triggered
            logger.info(f"Timing sensor on GPIO {sensor_pin}")
            
            # Arm sensor (IR) to arm the system
            arm_pin = self.config['gpio'].get('arm_pin')
            if arm_pin:
                self.arm_button = Button(
                    arm_pin, 
                    pull_up=True, 
                    bounce_time=0.5
                )
                self.arm_button.when_pressed = self._arm_sensor_triggered
                logger.info(f"Arm sensor (IR) on GPIO {arm_pin}")
                
        except Exception as e:
            logger.error(f"GPIO error: {e}")
            logger.warning("Continuing without local GPIO - using network sensors only")
    
    def _local_sensor_triggered(self):
        """Callback for local sensor (hog_close)."""
        trigger_time = time.time_ns()
        self._handle_trigger('hog_close', trigger_time)
    
    def _arm_sensor_triggered(self):
        """Callback for arm sensor (IR)."""
        logger.info("Arm sensor triggered!")
        self.arm()
    
    def start_udp_listener(self):
        """Start UDP listener in its own thread."""
        self._running = True
        self._udp_thread = threading.Thread(target=self._udp_listener_loop, daemon=True)
        self._udp_thread.start()
        logger.info("UDP-lyssnare startad")
    
    def stop_udp_listener(self):
        self._running = False
        self.udp_socket.close()
    
    def _udp_listener_loop(self):
        """Listen for UDP messages."""
        while self._running:
            try:
                data, addr = self.udp_socket.recvfrom(1024)
                payload = json.loads(data.decode('utf-8'))
                
                msg_type = payload.get('type')
                if msg_type == 'trigger':
                    device_id = payload.get('device_id')
                    timestamp_ns = payload.get('timestamp_ns')
                    if device_id:
                        self._mark_sensor_seen(device_id, addr, source='trigger')
                    if device_id and timestamp_ns:
                        self._handle_trigger(device_id, timestamp_ns)
                elif msg_type == 'heartbeat':
                    device_id = payload.get('device_id')
                    if device_id:
                        self._mark_sensor_seen(device_id, addr, source='heartbeat')
                        
            except OSError:
                break
            except json.JSONDecodeError as e:
                logger.error(f"Ogiltigt JSON: {e}")

    def _mark_sensor_seen(self, device_id: str, addr, source: str):
        """Record that a sensor was seen recently (heartbeat or trigger)."""
        try:
            ip, port = addr
        except Exception:
            ip, port = None, None
        self.sensor_last_seen[str(device_id)] = {
            'last_seen_ts': time.time(),
            'ip': ip,
            'port': port,
            'source': source
        }

    def get_sensors_status(self) -> dict:
        """Return sensor liveness status for the UI."""
        now = time.time()
        # Always show these three sensors in the UI; hog_close is local on the Pi 4.
        sensors = [
            {'device_id': 'tee', 'label': 'Tee'},
            {'device_id': 'hog_close', 'label': 'Hog near'},
            {'device_id': 'hog_far', 'label': 'Hog far'},
        ]

        out = []
        for s in sensors:
            device_id = s['device_id']
            meta = self.sensor_last_seen.get(device_id)

            # Local hog_close doesn't send heartbeat; mark as "local" (neutral) unless we've seen a trigger.
            if device_id == 'hog_close' and meta is None:
                out.append({
                    **s,
                    'status': 'local',
                    'last_seen_s_ago': None,
                    'ip': None,
                    'source': None
                })
                continue

            if meta is None:
                out.append({
                    **s,
                    'status': 'offline',
                    'last_seen_s_ago': None,
                    'ip': None,
                    'source': None
                })
                continue

            age = float(now - float(meta.get('last_seen_ts', now)))
            status = 'online' if age <= self.sensor_timeout_s else 'offline'
            out.append({
                **s,
                'status': status,
                'last_seen_s_ago': round(age, 1),
                'ip': meta.get('ip'),
                'source': meta.get('source')
            })

        return {'timeout_s': self.sensor_timeout_s, 'sensors': out}
    
    def _handle_trigger(self, device_id: str, timestamp_ns: int):
        """Handle a trigger from a sensor."""
        logger.info(f"Trigger: {device_id}")
        
        # hog_far can arrive after COMPLETED - update the latest measurement
        if device_id == 'hog_far' and self.state == SystemState.COMPLETED:
            if not self.session.hog_far_time_ns:
                self.session.hog_far_time_ns = timestamp_ns
                self._update_last_record()
                self.broadcast_state()
            return
        
        # Otherwise ignore if we are not ready to measure
        if self.state not in [SystemState.ARMED, SystemState.MEASURING]:
            logger.debug(f"Ignoring trigger from {device_id} - not armed")
            return
        
        # First trigger starts the measurement
        if self.state == SystemState.ARMED:
            self.state = SystemState.MEASURING
            self.session.started_at = datetime.now()
            self._measurement_token += 1
            self._schedule_auto_rearm(self._measurement_token)
        
        # Record timestamp (first only for each sensor, in correct order)
        if device_id == 'tee' and not self.session.tee_time_ns:
            self.session.tee_time_ns = timestamp_ns
            
        elif device_id == 'hog_close' and not self.session.hog_close_time_ns:
            # Ignore if hog_close arrives before tee (invalid order)
            if self.session.tee_time_ns and timestamp_ns > self.session.tee_time_ns:
                self.session.hog_close_time_ns = timestamp_ns
                # Measurement is \"complete\" after hog_close - save immediately
                self._complete_measurement()
            else:
                logger.debug("Ignoring hog_close - arrived before tee")
            
        elif device_id == 'hog_far' and not self.session.hog_far_time_ns:
            # Ignore if hog_far arrives before hog_close (invalid order)
            if self.session.hog_close_time_ns and timestamp_ns > self.session.hog_close_time_ns:
                self.session.hog_far_time_ns = timestamp_ns
                self._update_last_record()
            else:
                logger.debug("Ignoring hog_far - arrived before hog_close")
        
        self.broadcast_state()
    
    def _complete_measurement(self):
        """Complete measurement after hog_close."""
        self.state = SystemState.COMPLETED
        
        record = TimingRecord(
            id=self._next_id,
            timestamp=self.session.started_at,
            tee_to_hog_close_ms=self.session.tee_to_hog_close_ms,
            hog_to_hog_ms=None,  # Filled if the stone reaches hog_far
            total_ms=None
        )
        self._next_id += 1
        self.history.insert(0, record)
        
        if len(self.history) > 100:
            self.history = self.history[:100]
        
        logger.info(f"Complete: TEE→HOG={self.session.tee_to_hog_close_ms:.1f}ms")
        
        # Speak tee-hog time
        self._speak_time(self.session.tee_to_hog_close_ms, 'tee_hog')
    
    def _update_last_record(self):
        """Update the latest measurement with hog_far time."""
        if self.history:
            self.history[0].hog_to_hog_ms = self.session.hog_to_hog_ms
            self.history[0].total_ms = self.session.total_ms
            hog_hog = self.session.hog_to_hog_ms
            total = self.session.total_ms
            if hog_hog and total:
                logger.info(f"Updated: HOG→HOG={hog_hog:.1f}ms, Total={total:.1f}ms")
                # Speak hog-hog time
                self._speak_time(hog_hog, 'hog_hog')

    def _speak_phrase(self, text: str):
        """Speak a short phrase via Piper (or fallback TTS)."""
        if not self.speech_settings.get('speech_enabled', False):
            return
        if not text:
            return

        try:
            speak_script = '/opt/piper/speak.sh'
            if os.path.exists(speak_script):
                self._spawn_tts(text)
            else:
                subprocess.Popen(
                    ['/usr/bin/espeak-ng', '-v', 'en', '-s', '150', text],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=self._tts_env()
                )
        except Exception as e:
            logger.error(f"TTS error: {e}\n{traceback.format_exc()}")
    
    def _speak_time(self, time_ms: float, time_type: str = 'tee_hog'):
        """Speak a time value via text-to-speech."""
        if not self.speech_settings.get('speech_enabled', False):
            logger.debug("Speech is disabled")
            return
        
        # Check whether this time type should be spoken
        if time_type == 'tee_hog' and not self.speech_settings.get('speak_tee_hog', True):
            return
        if time_type == 'hog_hog' and not self.speech_settings.get('speak_hog_hog', False):
            return
            
        if time_ms is None or time_ms <= 0:
            return
            
        try:
            # Convert to seconds
            seconds = time_ms / 1000.0
            
            # Format exactly like the UI and speak it.
            # We speak hundredths in a more natural way:
            # - "3.10" -> "3 point 10"
            # - "3.06" -> "3 point oh 6"
            # - "3.00" -> "3 point 00"
            formatted = f"{seconds:.2f}"  # "3.18"
            whole, dec = formatted.split('.')  # dec is always 2 digits
            if dec == "00":
                dec_spoken = "00"
            elif dec.startswith("0"):
                dec_spoken = f"oh {dec[1]}"
            else:
                dec_spoken = dec
            text = f"{whole} point {dec_spoken}"
            
            logger.info(f"Speaking: '{text}'")
            
            # Try Piper script first, then fallback to espeak-ng
            speak_script = '/opt/piper/speak.sh'
            
            if os.path.exists(speak_script):
                # Non-blocking so UI updates aren't delayed while TTS plays
                logger.info(f"Spawning: {speak_script} '{text}'")
                self._spawn_tts(text)
            else:
                logger.warning("speak.sh not found, using espeak-ng")
                subprocess.Popen(
                    ['/usr/bin/espeak-ng', '-v', 'en', '-s', '150', text],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=self._tts_env()
                )
        except FileNotFoundError:
            logger.warning("TTS not installed")
        except Exception as e:
            logger.error(f"TTS error: {e}")
    
    def arm(self, force: bool = False):
        """Arm the system.

        Normal behavior: only allow IDLE/COMPLETED -> ARMED.
        If force=True, also allow MEASURING -> ARMED (used by auto-rearm timeout).
        """
        if not force and self.state not in [SystemState.IDLE, SystemState.COMPLETED]:
            return False
        if force and self.state not in [SystemState.IDLE, SystemState.COMPLETED, SystemState.MEASURING]:
            return False
        
        self.session.reset()
        self.state = SystemState.ARMED
        logger.info("ARMED")
        self._cancel_auto_rearm()
        # Broadcast first so UI updates instantly, then speak (which is non-blocking anyway)
        self.broadcast_state()
        if self.speech_settings.get('speak_ready', True):
            self._speak_phrase("ready to go")
        return True
    
    def disarm(self):
        """Disarm."""
        self.state = SystemState.IDLE
        self.session.reset()
        logger.info("DISARMED")
        self._cancel_auto_rearm()
        self.broadcast_state()
        return True

    def _cancel_auto_rearm(self):
        fut = self._auto_rearm_future
        self._auto_rearm_future = None
        try:
            if fut is not None and not fut.done():
                fut.cancel()
        except Exception:
            pass

    def _schedule_auto_rearm(self, token: int):
        """Schedule a forced arm back to ARMED if we remain stuck in MEASURING."""
        self._cancel_auto_rearm()
        if not self.speech_settings.get('auto_rearm_enabled', False):
            return
        try:
            after_s = float(self.speech_settings.get('auto_rearm_after_s', 120))
        except Exception:
            after_s = 120.0
        if after_s <= 0:
            return

        if self._loop and self._loop.is_running():
            self._auto_rearm_future = asyncio.run_coroutine_threadsafe(
                self._auto_rearm_after_delay(token, after_s),
                self._loop
            )

    async def _auto_rearm_after_delay(self, token: int, after_s: float):
        await asyncio.sleep(after_s)
        # Only act if we are still on the same "measurement" and still measuring.
        if token != self._measurement_token:
            return
        # Auto-rearm regardless of whether all sensors were seen.
        # If we're still MEASURING (hung run) or COMPLETED (run finished but user didn't rearm),
        # force the system back to ARMED.
        if self.state not in (SystemState.MEASURING, SystemState.COMPLETED):
            return
        logger.info(f"Auto-rearm timeout: {after_s:.0f}s since first trigger, forcing ARMED")
        self.arm(force=True)

    def _load_runtime_settings(self) -> None:
        """Load persisted settings overrides (best-effort)."""
        try:
            if not RUNTIME_SETTINGS_PATH.exists():
                return
            data = json.loads(RUNTIME_SETTINGS_PATH.read_text(encoding='utf-8') or '{}')
            if not isinstance(data, dict):
                return
            for k in (
                'speech_enabled',
                'speak_tee_hog',
                'speak_hog_hog',
                'speak_ready',
                'auto_rearm_enabled',
                'auto_rearm_after_s',
            ):
                if k in data:
                    self.speech_settings[k] = data[k]
            logger.info(f"Loaded runtime settings from {RUNTIME_SETTINGS_PATH}: {data}")
        except Exception as e:
            logger.warning(f"Failed to load runtime settings: {e}")

    def save_runtime_settings(self) -> None:
        """Persist current settings overrides (best-effort, atomic write)."""
        try:
            payload = {
                'speech_enabled': bool(self.speech_settings.get('speech_enabled', False)),
                'speak_tee_hog': bool(self.speech_settings.get('speak_tee_hog', True)),
                'speak_hog_hog': bool(self.speech_settings.get('speak_hog_hog', False)),
                'speak_ready': bool(self.speech_settings.get('speak_ready', True)),
                'auto_rearm_enabled': bool(self.speech_settings.get('auto_rearm_enabled', False)),
                'auto_rearm_after_s': int(self.speech_settings.get('auto_rearm_after_s', 120)),
            }
            tmp = RUNTIME_SETTINGS_PATH.with_suffix('.tmp')
            tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding='utf-8')
            tmp.replace(RUNTIME_SETTINGS_PATH)
            logger.info(f"Saved runtime settings to {RUNTIME_SETTINGS_PATH}: {payload}")
        except Exception as e:
            logger.warning(f"Failed to save runtime settings: {e}")
    
    def get_history(self, limit: int = 50) -> list[dict]:
        return [
            {
                'id': r.id,
                'timestamp': r.timestamp.isoformat(),
                'tee_to_hog_close_ms': r.tee_to_hog_close_ms,
                'hog_to_hog_ms': r.hog_to_hog_ms,
                'total_ms': r.total_ms
            }
            for r in self.history[:limit]
        ]
    
    def delete_record(self, record_id: int) -> bool:
        for i, r in enumerate(self.history):
            if r.id == record_id:
                self.history.pop(i)
                return True
        return False
    
    def clear_history(self):
        self.history.clear()
        self._next_id = 1
    
    def get_state(self) -> dict:
        return {
            'state': self.state.value,
            'session': self.session.to_dict(),
            'sensors': {}
        }
    
    def broadcast_state(self):
        """Broadcast state to all clients (thread-safe)."""
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._broadcast_state(), self._loop)
    
    async def _broadcast_state(self):
        state = self.get_state()
        message = json.dumps({'type': 'state_update', 'data': state})

        # Iterate over a snapshot so connect/disconnect can't break iteration.
        dead: list[WebSocket] = []
        for ws in list(self.websocket_clients):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)

        # Drop dead sockets so the list does not grow forever.
        for ws in dead:
            try:
                self.websocket_clients.remove(ws)
            except ValueError:
                pass


# Global server-instans
server = RockTimerServer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    server._loop = asyncio.get_running_loop()
    server.setup_gpio()
    server.start_udp_listener()
    # Optional: arm immediately on boot so you don't need to press Rearm the first time.
    if server.config.get('server', {}).get('auto_arm_on_start', False):
        server.arm()
    yield
    server.stop_udp_listener()
    # gpiozero hanterar cleanup automatiskt


app = FastAPI(title="RockTimer", version="1.0.0", lifespan=lifespan)


@app.post("/api/arm")
async def arm_system():
    success = server.arm()
    return {"success": success, "state": server.state.value}


@app.post("/api/disarm")
async def disarm_system():
    success = server.disarm()
    return {"success": success, "state": server.state.value}


@app.get("/api/status")
async def get_status():
    return server.get_state()


@app.get("/api/sensors")
async def get_sensors():
    return server.get_sensors_status()


@app.get("/api/current")
async def get_current():
    return server.session.to_dict()


@app.get("/api/times")
async def get_times(limit: int = 50):
    return server.get_history(limit)


@app.post("/api/clear")
async def clear_times_legacy():
    server.clear_history()
    return {"success": True}


@app.get("/api/settings")
async def get_settings():
    return server.speech_settings


@app.post("/api/settings")
async def update_settings(request: Request):
    settings = await request.json()
    server.speech_settings['speech_enabled'] = settings.get('speech_enabled', False)
    server.speech_settings['speak_tee_hog'] = settings.get('speak_tee_hog', True)
    server.speech_settings['speak_hog_hog'] = settings.get('speak_hog_hog', False)
    server.speech_settings['speak_ready'] = settings.get('speak_ready', True)
    # Auto-rearm (optional)
    server.speech_settings['auto_rearm_enabled'] = bool(settings.get('auto_rearm_enabled', False))
    try:
        after_s = int(settings.get('auto_rearm_after_s', server.speech_settings.get('auto_rearm_after_s', 120)))
    except Exception:
        after_s = int(server.speech_settings.get('auto_rearm_after_s', 120))
    # Clamp to sane range: 0..30 min
    after_s = max(0, min(after_s, 30 * 60))
    server.speech_settings['auto_rearm_after_s'] = after_s
    # Persist so it survives restarts
    server.save_runtime_settings()
    logger.info(f"Settings uppdaterade: {server.speech_settings}")
    return {"success": True}


@app.delete("/api/times/{record_id}")
async def delete_time(record_id: int):
    return {"success": server.delete_record(record_id)}


@app.delete("/api/times")
async def clear_times():
    server.clear_history()
    return {"success": True}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    server.websocket_clients.append(websocket)
    
    try:
        await websocket.send_text(json.dumps({'type': 'state_update', 'data': server.get_state()}))
        
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message.get('type') == 'arm':
                server.arm()
            elif message.get('type') == 'disarm':
                server.disarm()

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket error")
    finally:
        try:
            server.websocket_clients.remove(websocket)
        except ValueError:
            pass


static_path = Path(__file__).parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=static_path), name="static")


@app.get("/favicon.ico")
async def favicon():
    # Serve a tiny SVG favicon (text-based) so kiosk loading probes can reliably detect "server up".
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="12" fill="#000"/>
  <circle cx="32" cy="32" r="18" fill="#fff"/>
  <circle cx="32" cy="32" r="10" fill="#111"/>
</svg>"""
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/", response_class=HTMLResponse)
async def root():
    index_path = static_path / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return HTMLResponse("<h1>RockTimer</h1>")


def main():
    uvicorn.run(
        app,
        host=server.config['server']['host'],
        port=server.config['server']['http_port'],
        log_level="info"
    )


if __name__ == '__main__':
    main()
