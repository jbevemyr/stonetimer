#!/usr/bin/env python3
"""
RockTimer Sensor Daemon
Runs on Pi Zero 2 W at the tee line and the far hog line.
Monitors the light sensor and sends timestamps over UDP.
"""

import socket
import time
import json
import yaml
import logging
import signal
import sys
import threading
from pathlib import Path
from typing import Optional

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

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('rocktimer-sensor')


class SensorDaemon:
    """Main sensor daemon class for remote timing sensors.
    
    Runs on Pi Zero 2 W units at the tee line and far hog line.
    
    Responsibilities:
    - Monitor GPIO pin for laser trip sensor (LM393)
    - Capture high-precision timestamp (nanoseconds) on trigger
    - Send trigger event to server via UDP
    - Best-effort sending over UDP (no connection state to maintain)
    
    The sensor runs continuously and sends triggers regardless of server state.
    The server decides whether to act on incoming triggers based on its state.
    """
    
    def __init__(self, config_path: Path = CONFIG_PATH):
        self.config = self._load_config(config_path)
        self.device_id = self.config['device_id']  # "tee" or "hog_far"
        self.running = True
        self.sensor_button = None  # gpiozero Button for the sensor
        self._heartbeat_thread: Optional[threading.Thread] = None
        
        # UDP socket
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server_address = (
            self.config['server']['host'],
            self.config['server']['port']
        )

        # Heartbeat interval (seconds). Allows the server UI to show which sensors are alive.
        self.heartbeat_interval_s = float(self.config.get('server', {}).get('heartbeat_interval_s', 5.0))
        
        logger.info(f"Sensor: {self.device_id}")
        logger.info(f"Server: {self.server_address}")
        logger.info(f"Heartbeat interval: {self.heartbeat_interval_s:.1f}s")
        
    def _load_config(self, config_path: Path) -> dict:
        """Load configuration from YAML file."""
        if not config_path.exists():
            raise FileNotFoundError(f"Config file missing: {config_path}")
        
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    
    def _setup_gpio(self):
        """Configure GPIO for the light sensor."""
        if not GPIO_AVAILABLE:
            logger.warning("GPIO not available - running in simulation mode")
            return
        
        try:
            pin = self.config['gpio']['sensor_pin']
            debounce_s = self.config['gpio']['debounce_ms'] / 1000.0
            
            self.sensor_button = Button(
                pin,
                pull_up=True,
                bounce_time=debounce_s
            )
            self.sensor_button.when_pressed = self._sensor_triggered
            
            logger.info(f"GPIO {pin} configured with debounce {debounce_s*1000:.0f}ms")
            
        except Exception as e:
            logger.error(f"GPIO error: {e}")
            logger.warning("Continuing without GPIO")
    
    def _sensor_triggered(self):
        """Callback when the sensor triggers (laser beam breaks)."""
        # Capture timestamp immediately
        trigger_time = time.time_ns()
        
        logger.info(f"TRIGGER! {self.device_id}")
        
        # Send via UDP - server decides whether to act on it
        payload = {
            'type': 'trigger',
            'device_id': self.device_id,
            'timestamp_ns': trigger_time
        }
        
        try:
            data = json.dumps(payload).encode('utf-8')
            self.udp_socket.sendto(data, self.server_address)
        except Exception as e:
            logger.error(f"Could not send UDP: {e}")

    def _send_heartbeat(self):
        """Send periodic heartbeats to the server."""
        # Send one immediately on startup.
        next_send = 0.0
        while self.running:
            now = time.time()
            if now >= next_send:
                payload = {
                    'type': 'heartbeat',
                    'device_id': self.device_id,
                    'timestamp_ns': time.time_ns()
                }
                try:
                    data = json.dumps(payload).encode('utf-8')
                    self.udp_socket.sendto(data, self.server_address)
                except Exception as e:
                    logger.error(f"Could not send heartbeat UDP: {e}")
                next_send = now + self.heartbeat_interval_s
            time.sleep(0.2)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info("Shutting down...")
        self.running = False
        self.udp_socket.close()
        # gpiozero hanterar cleanup automatiskt
        sys.exit(0)
    
    def run(self):
        """Start the sensor daemon."""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        self._setup_gpio()
        
        logger.info("Sensor daemon started - sending triggers to server")

        # Heartbeat thread (daemon so process can exit cleanly)
        self._heartbeat_thread = threading.Thread(target=self._send_heartbeat, daemon=True)
        self._heartbeat_thread.start()
        
        # Keep the process alive
        while self.running:
            time.sleep(1)


def main():
    daemon = SensorDaemon()
    daemon.run()


if __name__ == '__main__':
    main()
