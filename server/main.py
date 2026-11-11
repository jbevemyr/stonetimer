#!/usr/bin/env python3
"""
StoneTimer Central Server
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
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, Response
from pydantic import BaseModel, ValidationError, field_validator
import uvicorn

from timing import DEVICE_IDS, Event, EventKind, SystemState, TimingCore, TimingRecord

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

ROOT_DIR = Path(__file__).parent.parent
CONFIG_PATH = ROOT_DIR / "config.yaml"
STATIC_PATH = Path(__file__).parent / "static"

SPEAK_SCRIPT = '/opt/piper/speak.sh'
ESPEAK = '/usr/bin/espeak-ng'

AUTO_REARM_MAX_S = 30 * 60

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('stonetimer-server')


class Settings(BaseModel):
    """Runtime settings, changeable via /api/settings and persisted across restarts."""
    # Speech on the Pi's own speaker. Browsers/phones keep their own local switch.
    speech_enabled: bool = False
    speak_tee_hog: bool = True
    speak_hog_hog: bool = False
    speak_ready: bool = True
    # After the first trigger, force ARMED again if the run hasn't been rearmed
    # within auto_rearm_after_s (recovers from aborted runs / missed sensors).
    auto_rearm_enabled: bool = False
    auto_rearm_after_s: int = 120

    @field_validator('auto_rearm_after_s', mode='before')
    @classmethod
    def _clamp_after_s(cls, value):
        # Clients send seconds as int or float; clamp to 0..30 min.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return value
        return max(0, min(int(round(value)), AUTO_REARM_MAX_S))


class SettingsUpdate(BaseModel):
    """Partial update: fields left out keep their current value."""
    speech_enabled: Optional[bool] = None
    speak_tee_hog: Optional[bool] = None
    speak_hog_hog: Optional[bool] = None
    speak_ready: Optional[bool] = None
    auto_rearm_enabled: Optional[bool] = None
    auto_rearm_after_s: Optional[float] = None


def spoken_time(time_ms: float) -> str:
    """Format a time the way it is spoken, matching the two decimals in the UI.

    "3.18" -> "3 point 18", "3.06" -> "3 point oh 6", "3.00" -> "3 point 00"
    """
    whole, dec = f"{time_ms / 1000.0:.2f}".split('.')
    if dec != "00" and dec.startswith("0"):
        dec = f"oh {dec[1]}"
    return f"{whole} point {dec}"


def write_json_atomic(path: Path, payload) -> None:
    tmp = path.with_name(path.name + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


class StoneTimerServer:
    """Main class for the StoneTimer server.

    Responsibilities:
    - Listen for UDP triggers and heartbeats from remote sensors (Pi Zero units)
    - Handle local GPIO sensor (hog_close timing sensor on Pi 4)
    - Drive the timing state machine (see timing.TimingCore)
    - Broadcast state, history, sensor status and settings to WebSocket clients
    - Optional: speak times via TTS
    - Persist measurement history and runtime settings

    Triggers arrive on the UDP thread and on gpiozero's callback thread, while
    arm/disarm come from the event loop. All access to the state machine goes
    through self._lock; side effects (speech, disk, broadcast) happen after it
    is released.
    """

    def __init__(self, config: Optional[dict] = None, config_path: Path = CONFIG_PATH,
                 data_dir: Optional[Path] = None):
        self.config = config if config is not None else self._load_config(config_path)
        server_cfg = self.config.get('server', {}) or {}

        data_dir = data_dir or server_cfg.get('data_dir') or ROOT_DIR
        self.data_dir = Path(data_dir)
        self.settings_path = self.data_dir / "runtime_settings.json"
        self.history_path = self.data_dir / "history.json"

        self._lock = threading.RLock()
        self._history_io_lock = threading.Lock()
        self.core = TimingCore(
            max_history=int(server_cfg.get('max_history', 100)),
            history=self._load_history(),
        )

        self.websocket_clients: list[WebSocket] = []
        self._loop = None  # Event loop reference, set when the server starts

        # Sensor liveness tracking (remote sensors send periodic heartbeats).
        # Map: device_id -> { last_seen_ts, ip, port, source, offsets_ms }
        self.sensor_last_seen: dict[str, dict] = {}
        self.sensor_timeout_s: float = float(server_cfg.get('sensor_timeout_s', 12.0))
        # Warn when a sensor's clock appears to be this far from ours (see _clock_offset_ms).
        self.clock_skew_warn_ms: float = float(server_cfg.get('clock_skew_warn_ms', 25.0))
        self._clock_warned: set[str] = set()

        # Defaults come from config.yaml; the persisted runtime settings override them.
        speech_cfg = server_cfg.get('speech', {}) or {}
        auto_rearm_cfg = server_cfg.get('auto_rearm', {}) or {}
        defaults = Settings()
        self.settings = Settings(
            speech_enabled=server_cfg.get('enable_speech', defaults.speech_enabled),
            speak_tee_hog=speech_cfg.get('speak_tee_hog', defaults.speak_tee_hog),
            speak_hog_hog=speech_cfg.get('speak_hog_hog', defaults.speak_hog_hog),
            speak_ready=speech_cfg.get('speak_ready', defaults.speak_ready),
            auto_rearm_enabled=auto_rearm_cfg.get('enabled', defaults.auto_rearm_enabled),
            auto_rearm_after_s=auto_rearm_cfg.get('after_s', defaults.auto_rearm_after_s),
        )
        self._load_runtime_settings()

        self._auto_rearm_future = None  # concurrent.futures.Future from run_coroutine_threadsafe

        self.udp_socket: Optional[socket.socket] = None
        self._udp_thread = None
        self._running = False

    @property
    def state(self) -> SystemState:
        return self.core.state

    def _load_config(self, config_path: Path) -> dict:
        if not config_path.exists():
            raise FileNotFoundError(f"Config file missing: {config_path}")
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)

    # --- GPIO -----------------------------------------------------------

    def setup_gpio(self):
        """Configure GPIO for local sensors."""
        if not GPIO_AVAILABLE:
            logger.warning("GPIO not available - running without local sensors")
            return

        try:
            # Hog close timing sensor
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
        try:
            self.handle_trigger('hog_close', trigger_time)
        except Exception:
            logger.exception("Error handling local trigger")

    def _arm_sensor_triggered(self):
        """Callback for arm sensor (IR)."""
        logger.info("Arm sensor triggered!")
        try:
            self.arm()
        except Exception:
            logger.exception("Error handling arm sensor")

    # --- UDP ------------------------------------------------------------

    def start_udp_listener(self):
        """Bind the UDP socket and start the listener thread."""
        port = self.config['server']['udp_port']
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp_socket.bind(('0.0.0.0', port))
        self._running = True
        self._udp_thread = threading.Thread(target=self._udp_listener_loop, daemon=True)
        self._udp_thread.start()
        logger.info(f"UDP listener started on port {self.udp_socket.getsockname()[1]}")

    def stop_udp_listener(self):
        self._running = False
        if self.udp_socket is not None:
            self.udp_socket.close()

    def _udp_listener_loop(self):
        """Receive UDP messages until the socket is closed.

        Nothing a sensor (or anything else on the network) sends may kill this
        thread: if it dies the server looks healthy but never sees a trigger.
        """
        while self._running:
            try:
                data, addr = self.udp_socket.recvfrom(1024)
            except OSError:
                if not self._running:
                    break
                logger.exception("UDP receive failed")
                time.sleep(0.1)
                continue

            received_ns = time.time_ns()
            try:
                self._handle_datagram(data, addr, received_ns)
            except Exception:
                logger.exception(f"Error handling UDP message from {addr}: {data[:200]!r}")

    def _handle_datagram(self, data: bytes, addr, received_ns: int):
        try:
            payload = json.loads(data.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            logger.warning(f"Invalid UDP message from {addr}: {e}")
            return
        if not isinstance(payload, dict):
            logger.warning(f"Invalid UDP message from {addr}: not a JSON object")
            return

        msg_type = payload.get('type')
        device_id = payload.get('device_id')
        timestamp_ns = payload.get('timestamp_ns')
        if msg_type not in ('trigger', 'heartbeat'):
            return
        if device_id not in DEVICE_IDS:
            logger.warning(f"Ignoring {msg_type} from unknown device {device_id!r} ({addr})")
            return
        if isinstance(timestamp_ns, bool) or not isinstance(timestamp_ns, int):
            timestamp_ns = None

        # Only heartbeats feed the clock check: trigger resends are delayed on purpose.
        offset_ms = None
        if msg_type == 'heartbeat' and timestamp_ns is not None:
            offset_ms = (received_ns - timestamp_ns) / 1_000_000
        self._mark_sensor_seen(device_id, addr, source=msg_type, offset_ms=offset_ms)

        if msg_type == 'trigger' and timestamp_ns is not None:
            self.handle_trigger(device_id, timestamp_ns)

    # --- sensor status --------------------------------------------------

    def _mark_sensor_seen(self, device_id: str, addr, source: str, offset_ms: Optional[float] = None):
        """Record that a sensor was seen recently (heartbeat or trigger)."""
        try:
            ip, port = addr
        except Exception:
            ip, port = None, None
        with self._lock:
            meta = self.sensor_last_seen.setdefault(device_id, {'offsets_ms': deque(maxlen=6)})
            meta.update({
                'last_seen_ts': time.time(),
                'ip': ip,
                'port': port,
                'source': source,
            })
            if offset_ms is not None:
                meta['offsets_ms'].append(offset_ms)

    @staticmethod
    def _clock_offset_ms(meta: dict) -> Optional[float]:
        """Estimate (server clock - sensor clock) from recent heartbeats.

        Each sample is receive time minus the sensor's send timestamp, i.e. clock
        offset plus network delay. The delay is never negative, so the smallest
        recent sample is the best estimate. It can't see offsets smaller than
        the network delay, but it catches a sensor whose clock never synced or
        was stepped, which is what silently produces wrong times.
        """
        offsets = meta.get('offsets_ms')
        if not offsets:
            return None
        return min(offsets)

    def get_sensors_status(self) -> dict:
        """Return sensor liveness and clock status for the UI."""
        now = time.time()
        # Always show these three sensors in the UI; hog_close is local on the Pi 4.
        sensors = [
            {'device_id': 'tee', 'label': 'Tee'},
            {'device_id': 'hog_close', 'label': 'Hog near'},
            {'device_id': 'hog_far', 'label': 'Hog far'},
        ]

        out = []
        with self._lock:
            for s in sensors:
                device_id = s['device_id']
                meta = self.sensor_last_seen.get(device_id)

                if meta is None:
                    # Local hog_close doesn't send heartbeats; show it as "local" (neutral).
                    out.append({
                        **s,
                        'status': 'local' if device_id == 'hog_close' else 'offline',
                        'last_seen_s_ago': None,
                        'ip': None,
                        'source': None,
                        'clock_offset_ms': None,
                        'clock_ok': None,
                    })
                    continue

                age = now - meta['last_seen_ts']
                online = age <= self.sensor_timeout_s
                offset_ms = self._clock_offset_ms(meta) if online else None
                out.append({
                    **s,
                    'status': 'online' if online else 'offline',
                    'last_seen_s_ago': round(age, 1),
                    'ip': meta.get('ip'),
                    'source': meta.get('source'),
                    'clock_offset_ms': None if offset_ms is None else round(offset_ms, 1),
                    'clock_ok': None if offset_ms is None else abs(offset_ms) <= self.clock_skew_warn_ms,
                })

        return {
            'timeout_s': self.sensor_timeout_s,
            'clock_skew_warn_ms': self.clock_skew_warn_ms,
            'sensors': out,
        }

    def _log_clock_warnings(self, status: dict) -> None:
        for s in status['sensors']:
            device_id = s['device_id']
            if s['clock_ok'] is False and device_id not in self._clock_warned:
                self._clock_warned.add(device_id)
                logger.warning(
                    f"Clock offset for {device_id} is {s['clock_offset_ms']} ms "
                    f"(limit {self.clock_skew_warn_ms} ms) - times involving it are unreliable. "
                    f"Check chrony on the sensor."
                )
            elif s['clock_ok'] and device_id in self._clock_warned:
                self._clock_warned.discard(device_id)
                logger.info(f"Clock offset for {device_id} is back within limits")

    # --- state machine --------------------------------------------------

    def handle_trigger(self, device_id: str, timestamp_ns: int):
        """Handle a trigger from a sensor (any thread)."""
        with self._lock:
            events = self.core.handle_trigger(device_id, timestamp_ns)
            token = self.core.measurement_token
        if events:
            logger.info(f"Trigger: {device_id}")
        else:
            # Resent duplicates, triggers while not armed, out-of-order sensors
            logger.debug(f"Trigger ignored: {device_id}")
        self._process_events(events, token)

    def arm(self) -> bool:
        """Arm the system. Returns False if it was already armed."""
        with self._lock:
            events = self.core.arm()
            token = self.core.measurement_token
        self._process_events(events, token)
        return bool(events)

    def disarm(self) -> bool:
        with self._lock:
            events = self.core.disarm()
            token = self.core.measurement_token
        self._process_events(events, token)
        return True

    def _process_events(self, events: list[Event], token: int) -> None:
        """Perform the side effects of state machine events (outside the lock)."""
        if not events:
            return

        # Broadcast first so the UI updates instantly; speech is non-blocking anyway.
        self.broadcast_state()

        for event in events:
            if event.kind == EventKind.ARMED:
                logger.info("ARMED")
                self._cancel_auto_rearm()
                if self.settings.speak_ready:
                    self._speak("ready to go")
            elif event.kind == EventKind.DISARMED:
                logger.info("DISARMED")
                self._cancel_auto_rearm()
            elif event.kind == EventKind.MEASURING_STARTED:
                self._schedule_auto_rearm(token)
            elif event.kind == EventKind.TEE_HOG:
                logger.info(f"Complete: TEE→HOG={event.value:.1f}ms")
                self._history_changed()
                if self.settings.speak_tee_hog:
                    self._speak_time(event.value)
            elif event.kind == EventKind.HOG_HOG:
                logger.info(f"Updated: HOG→HOG={event.value:.1f}ms")
                self._history_changed()
                if self.settings.speak_hog_hog:
                    self._speak_time(event.value)

    def get_state(self) -> dict:
        with self._lock:
            return self.core.state_dict()

    def get_session(self) -> dict:
        with self._lock:
            return self.core.session.to_dict()

    # --- auto-rearm -----------------------------------------------------

    def _cancel_auto_rearm(self):
        fut = self._auto_rearm_future
        self._auto_rearm_future = None
        if fut is not None and not fut.done():
            fut.cancel()

    def _schedule_auto_rearm(self, token: int):
        """Schedule a forced arm back to ARMED if the run is never rearmed."""
        self._cancel_auto_rearm()
        settings = self.settings
        if not settings.auto_rearm_enabled or settings.auto_rearm_after_s <= 0:
            return

        if self._loop and self._loop.is_running():
            self._auto_rearm_future = asyncio.run_coroutine_threadsafe(
                self._auto_rearm_after_delay(token, float(settings.auto_rearm_after_s)),
                self._loop
            )

    async def _auto_rearm_after_delay(self, token: int, after_s: float):
        await asyncio.sleep(after_s)
        # Only act if we are still on the same run: either hung in MEASURING or
        # COMPLETED without anyone rearming.
        with self._lock:
            if token != self.core.measurement_token:
                return
            if self.core.state not in (SystemState.MEASURING, SystemState.COMPLETED):
                return
        logger.info(f"Auto-rearm timeout: {after_s:.0f}s since first trigger, forcing ARMED")
        self.arm()

    # --- speech ---------------------------------------------------------

    def _tts_env(self) -> dict:
        """Environment variables for TTS subprocesses.

        If you use the Pi 4 analog jack (bcm2835 Headphones), you typically want:
        ALSA_DEVICE=hw:0,0
        """
        env = dict(os.environ)
        env.setdefault('HOME', os.path.expanduser('~'))
        # systemd units often set a very minimal PATH; make sure common tools exist for speak.sh
        path = env.get('PATH', '')
        for directory in ('/usr/bin', '/bin'):
            if directory not in path.split(':'):
                path = f"{directory}:{path}" if path else directory
        env['PATH'] = path
        server_cfg = self.config.get('server', {}) or {}
        alsa_device = server_cfg.get('alsa_device')
        if alsa_device:
            env['ALSA_DEVICE'] = str(alsa_device)
        # Optional: only set ALSA_CARD if explicitly configured.
        alsa_card = server_cfg.get('alsa_card')
        if alsa_card is not None:
            env['ALSA_CARD'] = str(alsa_card)
        return env

    def _tts_debug_log_path(self) -> str:
        return (self.config.get('server', {}) or {}).get('tts_debug_log', '/var/log/stonetimer-tts-spawn.log')

    def _spawn_piper(self, text: str, env: dict) -> None:
        """Spawn the Piper helper script, sending its output to the TTS debug log."""
        debug_log = self._tts_debug_log_path()
        try:
            log_file = open(debug_log, 'a')
        except OSError as e:
            # Not being able to write the debug log must not silence speech.
            logger.warning(f"Cannot open TTS debug log {debug_log}: {e}")
            subprocess.Popen([SPEAK_SCRIPT, text], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, env=env, start_new_session=True)
            return

        with log_file as f:
            f.write(f"{datetime.now().isoformat()} spawn speak.sh text={text!r} "
                    f"ALSA_DEVICE={env.get('ALSA_DEVICE')!r} ALSA_CARD={env.get('ALSA_CARD')!r}\n")
            f.flush()
            # speak.sh stdout/stderr go to the same file to catch ALSA/aplay errors.
            subprocess.Popen([SPEAK_SCRIPT, text], stdout=f, stderr=f, env=env,
                             start_new_session=True)

    def _speak(self, text: str) -> None:
        """Speak a phrase on the Pi's speaker via Piper, falling back to espeak-ng.

        Non-blocking, so UI updates aren't delayed while TTS plays.
        """
        if not self.settings.speech_enabled or not text:
            return

        logger.info(f"Speaking: '{text}'")
        try:
            env = self._tts_env()
            if os.path.exists(SPEAK_SCRIPT):
                self._spawn_piper(text, env)
            else:
                subprocess.Popen(
                    [ESPEAK, '-v', 'en', '-s', '150', text],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env
                )
        except FileNotFoundError:
            logger.warning("TTS not installed")
        except Exception:
            logger.exception("TTS error")

    def _speak_time(self, time_ms: Optional[float]) -> None:
        if time_ms is None or time_ms <= 0:
            return
        self._speak(spoken_time(time_ms))

    # --- settings -------------------------------------------------------

    def _load_runtime_settings(self) -> None:
        """Load persisted settings overrides (best-effort)."""
        try:
            if not self.settings_path.exists():
                return
            data = json.loads(self.settings_path.read_text(encoding='utf-8') or '{}')
            if not isinstance(data, dict):
                raise ValueError("expected a JSON object")
            known = {k: v for k, v in data.items() if k in Settings.model_fields}
            self.settings = Settings(**{**self.settings.model_dump(), **known})
            logger.info(f"Loaded runtime settings from {self.settings_path}: {known}")
        except (OSError, ValueError, ValidationError) as e:
            logger.warning(f"Failed to load runtime settings: {e}")

    def get_settings(self) -> dict:
        return self.settings.model_dump()

    def update_settings(self, update: SettingsUpdate) -> dict:
        """Apply a partial settings update, persist it and tell the clients."""
        changes = update.model_dump(exclude_none=True)
        with self._lock:
            self.settings = Settings(**{**self.settings.model_dump(), **changes})
            payload = self.settings.model_dump()
        try:
            write_json_atomic(self.settings_path, payload)
        except OSError as e:
            logger.warning(f"Failed to save runtime settings: {e}")
        logger.info(f"Settings updated: {payload}")
        self._broadcast('settings', payload)
        return payload

    # --- history --------------------------------------------------------

    def _load_history(self) -> list[TimingRecord]:
        """Load persisted history (best-effort; a corrupt file must not stop the server)."""
        try:
            if not self.history_path.exists():
                return []
            data = json.loads(self.history_path.read_text(encoding='utf-8') or '[]')
            records = [TimingRecord.from_dict(item) for item in data]
            logger.info(f"Loaded {len(records)} measurements from {self.history_path}")
            return records
        except (OSError, ValueError, KeyError, TypeError) as e:
            logger.warning(f"Failed to load history from {self.history_path}: {e}")
            return []

    def _history_changed(self) -> None:
        """Persist the history and push it to the clients."""
        # Snapshot inside the I/O lock so the last writer always has the newest data.
        with self._history_io_lock:
            with self._lock:
                snapshot = self.core.history_dicts()
            try:
                write_json_atomic(self.history_path, snapshot)
            except OSError as e:
                logger.warning(f"Failed to save history: {e}")
        self._broadcast('history', snapshot)

    def get_history(self, limit: Optional[int] = 50) -> list[dict]:
        with self._lock:
            return self.core.history_dicts(limit)

    def delete_record(self, record_id: int) -> bool:
        with self._lock:
            deleted = self.core.delete_record(record_id)
        if deleted:
            self._history_changed()
        return deleted

    def clear_history(self):
        with self._lock:
            self.core.clear_history()
        self._history_changed()

    # --- WebSocket broadcast ---------------------------------------------

    def snapshot_messages(self) -> list[str]:
        """Everything a newly connected client needs."""
        return [
            json.dumps({'type': 'state_update', 'data': self.get_state()}),
            json.dumps({'type': 'history', 'data': self.get_history(None)}),
            json.dumps({'type': 'sensors', 'data': self.get_sensors_status()}),
            json.dumps({'type': 'settings', 'data': self.get_settings()}),
        ]

    def broadcast_state(self):
        self._broadcast('state_update', self.get_state())

    def _broadcast(self, msg_type: str, data) -> None:
        """Send a message to all WebSocket clients (thread-safe)."""
        if self._loop and self._loop.is_running():
            message = json.dumps({'type': msg_type, 'data': data})
            asyncio.run_coroutine_threadsafe(self._send_to_all(message), self._loop)

    async def _send_to_all(self, message: str):
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

    async def watch_sensors(self, interval_s: float = 1.0):
        """Push sensor status to the clients whenever it changes.

        Sensors go offline by timing out, so this has to be checked periodically.
        """
        last = None
        while True:
            try:
                status = self.get_sensors_status()
                summary = [(s['device_id'], s['status'], s['clock_ok']) for s in status['sensors']]
                if summary != last:
                    last = summary
                    self._log_clock_warnings(status)
                    await self._send_to_all(json.dumps({'type': 'sensors', 'data': status}))
            except Exception:
                logger.exception("Sensor watch failed")
            await asyncio.sleep(interval_s)


def create_app(server: StoneTimerServer) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        server._loop = asyncio.get_running_loop()
        server.setup_gpio()
        server.start_udp_listener()
        sensor_task = asyncio.create_task(server.watch_sensors())
        # Optional: arm immediately on boot so you don't need to press Rearm the first time.
        if (server.config.get('server', {}) or {}).get('auto_arm_on_start', False):
            server.arm()
        yield
        sensor_task.cancel()
        server.stop_udp_listener()
        # gpiozero cleans up after itself

    app = FastAPI(title="StoneTimer", version="1.0.0", lifespan=lifespan)
    app.state.server = server

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
        return server.get_session()

    @app.get("/api/times")
    async def get_times(limit: int = 50):
        return server.get_history(limit)

    @app.delete("/api/times/{record_id}")
    async def delete_time(record_id: int):
        return {"success": server.delete_record(record_id)}

    @app.delete("/api/times")
    async def clear_times():
        server.clear_history()
        return {"success": True}

    @app.post("/api/clear")
    async def clear_times_legacy():
        server.clear_history()
        return {"success": True}

    @app.get("/api/settings")
    async def get_settings():
        return server.get_settings()

    @app.post("/api/settings")
    async def update_settings(update: SettingsUpdate):
        return {"success": True, "settings": server.update_settings(update)}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        server.websocket_clients.append(websocket)

        try:
            for message in server.snapshot_messages():
                await websocket.send_text(message)

            while True:
                data = await websocket.receive_text()
                try:
                    message = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if not isinstance(message, dict):
                    continue

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

    if STATIC_PATH.exists():
        app.mount("/static", StaticFiles(directory=STATIC_PATH), name="static")

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
        index_path = STATIC_PATH / "index.html"
        if index_path.exists():
            return FileResponse(index_path)
        return HTMLResponse("<h1>StoneTimer</h1>")

    return app


def main():
    server = StoneTimerServer()
    uvicorn.run(
        create_app(server),
        host=server.config['server']['host'],
        port=server.config['server']['http_port'],
        log_level="info"
    )


if __name__ == '__main__':
    main()
