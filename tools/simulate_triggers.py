#!/usr/bin/env python3
"""
Simulate sensor triggers for testing.
Sends UDP messages directly to the server.
"""

import socket
import time
import json
import argparse
import random
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

DEFAULT_SERVER = "192.168.50.1"
DEFAULT_PORT = 5000
DEFAULT_HTTP_PORT = 8080

# Realistic timing ranges (seconds)
TEE_HOG_MIN = 2.80
TEE_HOG_MAX = 3.30
HOG_HOG_MIN = 8.0
HOG_HOG_MAX = 14.0


def _load_server_from_config(config_path: Path) -> Optional[Tuple[str, int, int]]:
    """Load (host, udp_port, http_port) from a RockTimer config.yaml if available."""
    if yaml is None:
        return None
    if not config_path.exists():
        return None
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        server = (cfg or {}).get("server", {}) or {}
        host = server.get("host") or DEFAULT_SERVER
        udp_port = int(server.get("udp_port") or server.get("port") or DEFAULT_PORT)
        http_port = int(server.get("http_port") or DEFAULT_HTTP_PORT)
        # If server binds to 0.0.0.0, clients should connect via loopback/real IP.
        if host == "0.0.0.0":
            host = "127.0.0.1"
        return host, udp_port, http_port
    except Exception:
        return None


def arm_server(server_host: str, http_port: int, timeout_s: float = 1.0) -> bool:
    """Best-effort: ask the RockTimer server to arm (rearm) via HTTP."""
    url = f"http://{server_host}:{http_port}/api/arm"
    req = urllib.request.Request(url, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            data = {}
        success = bool(data.get("success", True))
        state = data.get("state", "unknown")
        print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Rearm: success={success} state={state}")
        return success
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Rearm: failed ({e})")
        return False


def send_trigger(sock, server_addr, device_id: str):
    """Send a trigger event."""
    payload = {
        'type': 'trigger',
        'device_id': device_id,
        'timestamp_ns': time.time_ns()
    }
    
    data = json.dumps(payload).encode('utf-8')
    sock.sendto(data, server_addr)
    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Trigger: {device_id}")


def simulate_stone_pass(sock, server_addr, delay_tee_hog: float = None, delay_hog_hog: float = None, skip_far: bool = False):
    """Simulate a stone passing the sensors."""
    
    # Randomize times if not provided
    if delay_tee_hog is None:
        delay_tee_hog = random.uniform(TEE_HOG_MIN, TEE_HOG_MAX)
    if delay_hog_hog is None:
        delay_hog_hog = random.uniform(HOG_HOG_MIN, HOG_HOG_MAX)
    
    print(f"\n🥌 Simulating stone pass...")
    print(f"   Tee → Hog: {delay_tee_hog:.2f}s")
    if not skip_far:
        print(f"   Hog → Hog: {delay_hog_hog:.2f}s")
    else:
        print(f"   (Stone does not reach far hog)")
    print()
    
    # Tee
    send_trigger(sock, server_addr, "tee")
    
    # Hog close
    time.sleep(delay_tee_hog)
    send_trigger(sock, server_addr, "hog_close")
    
    # Hog far (if the stone reaches it)
    if not skip_far:
        time.sleep(delay_hog_hog)
        send_trigger(sock, server_addr, "hog_far")
    
    print("\n✓ Done!")


def main():
    parser = argparse.ArgumentParser(description="Simulate RockTimer triggers via UDP")
    parser.add_argument("--server", default=None, help="Server IP/hostname (default: from config.yaml if found, else 192.168.50.1)")
    parser.add_argument("--port", type=int, default=None, help="Server UDP port (default: from config.yaml if found, else 5000)")
    parser.add_argument("--http-port", type=int, default=None, help="Server HTTP port (for /api/arm) (default: from config.yaml if found, else 8080)")
    parser.add_argument("--config", default=None, help="Path to config.yaml (default: ./config.yaml, then /opt/rocktimer/config.yaml)")
    parser.add_argument("--device", choices=["tee", "hog_close", "hog_far"], 
                       help="Send a single trigger")
    parser.add_argument("--simulate", action="store_true", help="Simulate a full stone pass")
    parser.add_argument("--tee-hog", type=float, default=None, 
                       help=f"Tee→hog time in seconds (default: random {TEE_HOG_MIN}-{TEE_HOG_MAX})")
    parser.add_argument("--hog-hog", type=float, default=None,
                       help=f"Hog→hog time in seconds (default: random {HOG_HOG_MIN}-{HOG_HOG_MAX})")
    parser.add_argument("--skip-far", action="store_true", 
                       help="Simulate that the stone does not reach far hog")
    parser.add_argument("--loop", type=int, default=1,
                       help="Number of stone passes to simulate")
    parser.add_argument("--delay", type=float, default=3.0,
                       help="Seconds between stone passes when using --loop")
    
    args = parser.parse_args()

    # Resolve defaults from config when available (helps when running on the Pi 4 locally).
    config_candidates = []
    if args.config:
        config_candidates.append(Path(args.config))
    else:
        config_candidates.extend([Path("config.yaml"), Path("/opt/rocktimer/config.yaml")])

    cfg_resolved = None
    for p in config_candidates:
        cfg_resolved = _load_server_from_config(p)
        if cfg_resolved:
            break

    server_host = args.server or (cfg_resolved[0] if cfg_resolved else DEFAULT_SERVER)
    udp_port = int(args.port or (cfg_resolved[1] if cfg_resolved else DEFAULT_PORT))
    http_port = int(args.http_port or (cfg_resolved[2] if cfg_resolved else DEFAULT_HTTP_PORT))

    server_addr = (server_host, udp_port)
    print(f"Server: {server_addr[0]}:{server_addr[1]}")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    if args.device:
        send_trigger(sock, server_addr, args.device)
    elif args.simulate:
        for i in range(args.loop):
            if args.loop > 1:
                print(f"\n{'='*40}")
                print(f"Stone {i+1} of {args.loop}")
                print(f"{'='*40}")

            # Rearm between runs (and also before the first run) so each simulated stone is measured.
            arm_server(server_host, http_port)
            
            simulate_stone_pass(
                sock, server_addr, 
                args.tee_hog, args.hog_hog,
                args.skip_far
            )
            
            if i < args.loop - 1:
                print(f"\nWaiting {args.delay}s before next stone...")
                time.sleep(args.delay)
    else:
        print("\nNo command specified. Use --help for help.")
        print("\nExamples:")
        print("  python simulate_triggers.py --simulate              # One stone, random times")
        print("  python simulate_triggers.py --simulate --loop 5     # 5 stones")
        print("  python simulate_triggers.py --simulate --skip-far   # Stone that doesn't reach far hog")
        print("  python simulate_triggers.py --device tee            # Single trigger")
    
    sock.close()


if __name__ == '__main__':
    main()
