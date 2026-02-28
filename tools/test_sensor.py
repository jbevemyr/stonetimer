#!/usr/bin/env python3
"""
Test utility for the light sensor.
Run on the Pi to verify the sensor works.
"""

import argparse
import time
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("pyyaml is required. Install with: pip install pyyaml")
    sys.exit(1)

try:
    from gpiozero import Button
    from gpiozero.pins.lgpio import LGPIOFactory
    from gpiozero import Device
    Device.pin_factory = LGPIOFactory()
except ImportError:
    print("gpiozero + lgpio are required. Install with: sudo apt-get install -y python3-gpiozero python3-lgpio")
    sys.exit(1)

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


def load_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Config file missing: {path}")
    with open(path, "r") as f:
        return yaml.safe_load(f)


def on_trigger():
    """Callback when the sensor triggers (beam breaks)."""
    timestamp = time.time_ns()
    print(f"TRIGGER! Time: {timestamp} ns ({time.strftime('%H:%M:%S')})")


def main():
    parser = argparse.ArgumentParser(description="RockTimer light sensor test (gpiozero)")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config.yaml")
    parser.add_argument("--pin", type=int, default=None, help="Override GPIO pin (BCM numbering)")
    parser.add_argument("--debounce-ms", type=int, default=None, help="Override debounce (ms)")
    args = parser.parse_args()

    print("=================================")
    print("RockTimer Sensor Test")
    print("=================================")
    cfg = load_config(Path(args.config))
    cfg_gpio = (cfg.get("gpio") or {})
    pin = args.pin if args.pin is not None else int(cfg_gpio.get("sensor_pin", 17))
    debounce_ms = args.debounce_ms if args.debounce_ms is not None else int(cfg_gpio.get("debounce_ms", 50))
    debounce_s = debounce_ms / 1000.0

    print(f"Monitoring GPIO pin (BCM): {pin}")
    print(f"Debounce: {debounce_ms}ms")
    print("Break the beam to test")
    print("Press Ctrl+C to exit")
    print()

    # With pull_up=True, Button is considered "pressed" when the pin reads LOW.
    # For LM393-type sensor modules, DO typically goes LOW when the beam is blocked.
    btn = Button(pin, pull_up=True, bounce_time=debounce_s)
    btn.when_pressed = on_trigger

    print(f"Current state: {'LOW (blocked)' if btn.is_pressed else 'HIGH (light)'}")
    print()

    try:
        while True:
            status = "□ BLOCKED" if btn.is_pressed else "■ LIGHT"
            print(f"\rSensor: {status}  ", end="", flush=True)
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n\nExiting...")

if __name__ == '__main__':
    main()

