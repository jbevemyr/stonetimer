# RockTimer System Architecture

This document describes the technical architecture of RockTimer.

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CURLING SHEET                               │
│                                                                     │
│  TEE LINE          NEAR HOG LINE (back)      FAR HOG LINE (front)   │
│     │                     │                       │                 │
│     ▼                     ▼                       ▼                 │
│  ┌──────┐              ┌──────┐                ┌──────┐             │
│  │Laser │◄────────────►│Laser │◄──────────────►│Laser │             │
│  └──┬───┘              └──┬───┘                └──┬───┘             │
│     v                     v                       v                 │
│     v                     v                       v                 │
│     v                     v                       v                 │
│  ┌──────┐              ┌──────┐                ┌──────┐             │
│  │Sensor│◄────────────►│Sensor│◄──────────────►│Sensor│             │
│  │      │  ~10m        │      │    ~30m        │      │             │
│  └──┬───┘              └──┬───┘                └──┬───┘             │
│     │                     │                       │                 │
└─────┼─────────────────────┼───────────────────────┼─────────────────┘
      │                     │                       │
      │ GPIO 17             │ GPIO 17 + 27          │ GPIO 17
      │                     │ (IR sensor)           │
      ▼                     ▼                       ▼
   ┌─────────┐         ┌─────────┐             ┌─────────┐
   │Pi Zero 2│         │ Pi 4    │             │Pi Zero 2│
   │  "tee"  │         │"hog_close"            │"hog_far"│
   │         │         │         │             │         │
   │  UDP    │────────►│ SERVER  │◄────────────│  UDP    │
   │ Client  │  :5000  │         │   :5000     │ Client  │
   └─────────┘         │   Web   │             └─────────┘
                       │   :8080 │
                       │         │
                       │ Display │
                       │ Speaker │
                       └────┬────┘
                            │
                            │ WebSocket + HTTP
                            ▼
                      ┌──────────────┐
                      │  Web Browser │
                      │ (Touchscreen │
                      │  or Phone)   │
                      └──────────────┘
```

## Component Responsibilities

### Pi 4 (Central Server)

**Location:** Near hog line (back line)

**Hardware:**
- Raspberry Pi 4 Model B
- Touch display (5" recommended)
- Speaker + amplifier (optional)
- LM393 timing sensor (hog_close)
- IR proximity sensor (arm trigger)
- Power bank

**Software Components:**

1. **`server/main.py`** - FastAPI server
   - HTTP API endpoints (`/api/*`)
   - WebSocket server (`/ws`)
   - UDP listener (port 5000)
   - State machine (idle → armed → measuring → completed)
   - History tracking
   - TTS integration

2. **Kiosk Mode** (`rocktimer-kiosk.service`)
   - Chromium in fullscreen
   - Auto-start on boot
   - Touch-optimized

3. **Network Services**
   - `hostapd` - Wi-Fi Access Point
   - `dnsmasq` - DHCP + DNS
   - `chrony` - NTP time server

**State Machine:**

```
┌──────┐  arm()   ┌───────┐  first   ┌───────────┐  hog_close  ┌───────────┐
│ IDLE ├─────────►│ ARMED ├─trigger─►│ MEASURING ├────────────►│ COMPLETED │
└──────┘          └───────┘          └───────────┘             └─────┬─────┘
   ▲                                                                 │
   └─────────────────────────────────────────────────────────────────┘
                          rearm() or timeout
```

### Pi Zero 2 W (Remote Sensors)

**Locations:**
- Tee line (device_id: "tee")
- Far hog line (device_id: "hog_far")

**Hardware:**
- Raspberry Pi Zero 2 W
- LM393 timing sensor
- Power bank

**Software Components:**

1. **`sensor/sensor_daemon.py`** - Sensor daemon
   - GPIO monitoring (gpiozero)
   - Timestamp capture (nanosecond precision)
   - UDP message sender
   - Runs as systemd service

**Operation:**
- Continuously monitors GPIO 17
- On trigger (laser beam break):
  1. Capture `time.time_ns()`
  2. Build JSON payload
  3. Send via UDP to server
- No state management (stateless)

### Web UI (`server/static/index.html`)

**Features:**
- Real-time display via WebSocket
- Touch-optimized buttons (large targets)
- Responsive design (works on phones)
- History table with scrolling
- Settings modal (speech config)

**Technologies:**
- Vanilla JavaScript (no framework)
- CSS Grid/Flexbox layout
- WebSocket API
- Fetch API for HTTP requests

## Data Flow

### Typical Measurement Sequence

```
1. USER arms system (via button or IR sensor)
   └─► Server state: IDLE → ARMED
       └─► WebSocket broadcast: state_update
           └─► UI: status dot turns green
               └─► Optional: TTS speaks "ready to go"

2. Stone released, breaks TEE sensor
   └─► Pi Zero "tee" captures timestamp (t1)
       └─► UDP → Server :5000
           └─► Server: ARMED → MEASURING
               └─► Session.tee_time_ns = t1
                   └─► WebSocket broadcast

3. Stone passes NEAR HOG sensor
   └─► Pi 4 local GPIO interrupt (t2)
       └─► Server calculates: t2 - t1 = tee_to_hog_ms
           └─► Server: MEASURING → COMPLETED
               └─► Save to history
                   └─► TTS speaks time: "3 point 18"
                       └─► WebSocket broadcast
                           └─► UI displays time

4. Stone passes FAR HOG sensor (optional)
   └─► Pi Zero "hog_far" captures timestamp (t3)
       └─► UDP → Server :5000
           └─► Server updates last measurement
               └─► Calculate: t3 - t2 = hog_to_hog_ms
                   └─► Optional: TTS speaks hog-hog time
                       └─► WebSocket broadcast
```

## Network Architecture

### Wi-Fi Access Point (Pi 4)

```
┌───────────────────────────────────────────────────────────┐
│ Pi 4 (192.168.50.1)                                       │
│                                                           │
│ ┌────────────┐  ┌──────────┐  ┌────────────┐              │
│ │  hostapd   │  │ dnsmasq  │  │   chrony   │              │
│ │ (AP mode)  │  │ DHCP+DNS │  │ NTP server │              │
│ └────────────┘  └──────────┘  └────────────┘              │
│       │                │               │                  │
│       └────────────────┴───────────────┘                  │
│                        │                                  │
│                     wlan0                                 │
│                   SSID: rocktimer                         │
│                   PSK: rocktimer                          │
└────────────────────────┬──────────────────────────────────┘
                         │
          ┌──────────────┴──────────────┬─────────────────┐
          │                             │                 │
    ┌─────▼─────┐                 ┌─────▼─────┐    ┌─────▼─────┐
    │ Pi Zero   │                 │ Pi Zero   │    │  Phone /  │
    │  "tee"    │                 │ "hog_far" │    │  Tablet   │
    │ .50.10    │                 │ .50.11    │    │  .50.15   │
    └───────────┘                 └───────────┘    └───────────┘
```

**Services:**
- **hostapd:** Creates "rocktimer" Wi-Fi network
- **dnsmasq:** 
  - DHCP: assigns 192.168.50.10-100
  - DNS: resolves "rocktimer" → 192.168.50.1
- **chrony:** Time synchronization (critical for accurate timing)

### Time Synchronization

**Why it matters:** Sensors are on different devices. If their clocks differ by 10ms, measurements will be off by 10ms.

**Solution:** chrony NTP

```
External NTP     ┌──────────────────┐
  (internet) ───►│ Pi 4 chrony      │ stratum 10 (local reference)
                 │ 192.168.50.1     │
                 └────────┬─────────┘
                          │ NTP
         ┌────────────────┴────────────────┐
         │                                 │
    ┌────▼────┐                      ┌────▼────┐
    │Pi Zero  │                      │Pi Zero  │
    │chrony   │                      │chrony   │
    │client   │                      │client   │
    └─────────┘                      └─────────┘
```

**Expected accuracy:** < 1ms offset after sync

**Check sync:**
```bash
chronyc tracking    # View current offset
chronyc sources -v  # View time sources
```

## Protocols

### UDP Trigger Message

**Format:** JSON over UDP

**Example:**
```json
{
  "type": "trigger",
  "device_id": "tee",
  "timestamp_ns": 1703265432123456789
}
```

**Why UDP?**
- Low latency (no TCP handshake)
- Fire-and-forget (sensor doesn't wait for ACK)
- Simple (no connection management)
- Reliable enough on local Wi-Fi (<1% packet loss)

**Packet loss handling:**
- Each trigger is independent
- If a tee trigger is lost, the stone simply won't be measured
- User can visually confirm triggers (laser beam break = immediate)

### WebSocket State Updates

**Format:** JSON over WebSocket

**Example:**
```json
{
  "type": "state_update",
  "data": {
    "state": "completed",
    "session": {
      "tee_time_ns": 1703265432123456789,
      "hog_close_time_ns": 1703265435223456789,
      "hog_far_time_ns": 1703265445523456789,
      "tee_to_hog_close_ms": 3100.0,
      "hog_to_hog_ms": 10300.0,
      "total_ms": 13400.0,
      "has_hog_close": true,
      "has_hog_far": true,
      "started_at": "2024-12-22T15:30:32.123456"
    },
    "sensors": {}
  }
}
```

**Client → Server commands:**
```json
{"type": "arm"}
{"type": "disarm"}
```

## File Structure

```
rocktimer/
├── server/
│   ├── main.py              # FastAPI server (Pi 4)
│   └── static/
│       └── index.html       # Web UI
├── sensor/
│   └── sensor_daemon.py     # Sensor daemon (Pi Zero)
├── setup/
│   ├── setup_network.sh     # Configure Wi-Fi AP
│   ├── setup_nginx_proxy.sh # Optional: port 80 reverse proxy
│   ├── setup_splash.sh      # Boot splash screen
│   ├── chrony-server.conf   # Time sync config (Pi 4)
│   └── chrony-client.conf   # Time sync config (Pi Zero)
├── configs/
│   ├── config-pi4-hog-close.yaml
│   ├── config-zero-tee.yaml
│   └── config-zero-hog-far.yaml
├── tools/
│   ├── simulate_triggers.py # UDP trigger simulator
│   └── test_sensor.py       # GPIO sensor test
├── apple-watch/             # Optional Apple Watch companion
├── install_server.sh        # Pi 4 installer
├── install_sensor.sh        # Pi Zero installer
├── config.yaml.example      # Configuration template
├── requirements-server.txt  # Python deps (Pi 4)
├── requirements-sensor.txt  # Python deps (Pi Zero)
├── README.md                # Main documentation
├── QUICKSTART.md            # Getting started guide
└── ARCHITECTURE.md          # This file
```

## Systemd Services

### Server (Pi 4)

**`/etc/systemd/system/rocktimer-server.service`**
- Runs: `/opt/rocktimer/venv/bin/python /opt/rocktimer/server/main.py`
- User: root (required for GPIO)
- Restart: always
- Logs: `journalctl -u rocktimer-server`

**`/etc/systemd/system/rocktimer-kiosk.service`**
- Runs: Chromium in kiosk mode
- User: pi (regular user, for X11 access)
- After: graphical.target, rocktimer-server.service
- Restart: always

### Sensor (Pi Zero)

**`/etc/systemd/system/rocktimer-sensor.service`**
- Runs: `/opt/rocktimer/venv/bin/python /opt/rocktimer/sensor/sensor_daemon.py`
- User: root (required for GPIO)
- Restart: always
- Logs: `journalctl -u rocktimer-sensor`

## Configuration Files

### `/opt/rocktimer/config.yaml`

**Used by:** Both server and sensor daemons

**Key settings:**
```yaml
device_id: "tee"              # Sensor identity
gpio:
  sensor_pin: 17              # GPIO for LM393
  debounce_ms: 50             # Debounce time
server:
  host: "192.168.50.1"        # Server IP
  port: 5000                  # UDP port
  http_port: 8080             # Web UI port
  enable_speech: true         # TTS on/off
  speech:
    speak_tee_hog: true       # Announce tee-hog time
```

### `/etc/hostapd/hostapd.conf`

**Used by:** hostapd (Wi-Fi AP)

**Created by:** `setup/setup_network.sh`

### `/etc/dnsmasq.conf`

**Used by:** dnsmasq (DHCP + DNS)

**Key features:**
- DHCP range: 192.168.50.10-100
- DNS: "rocktimer" → 192.168.50.1
- Captive portal bypass (for phones)

### `/etc/chrony/chrony.conf`

**Used by:** chrony (time sync)

**Pi 4 (server):**
```
allow 192.168.50.0/24    # Allow clients
local stratum 10         # Act as local time source
makestep 1.0 3          # Step clock if offset > 1s
```

**Pi Zero (clients):**
```
server 192.168.50.1 iburst prefer
makestep 1.0 3
```

## Performance Characteristics

### Timing Accuracy

**Factors affecting accuracy:**
1. **Clock sync:** chrony keeps clocks within ~0.5ms
2. **GPIO interrupt latency:** ~50-100μs on Linux
3. **Network latency:** ~1-5ms on local Wi-Fi
4. **Sensor response time:** ~1ms (LM393 module)

**Expected total error:** ±5-10ms

**Good enough?** Yes. For curling timing:
- 10ms error at 3000ms = 0.3% error
- Stone moves ~0.5cm in 10ms (negligible)

### System Latency

**Trigger → UI update:**
1. GPIO interrupt: <0.1ms
2. Python callback: ~1ms
3. WebSocket send: ~5ms
4. Browser render: ~16ms (60fps)

**Total:** ~25ms from beam break to screen update

### Throughput

**UDP triggers:** 1000+ per second (not a bottleneck)

**WebSocket clients:** Up to 100 simultaneous (FastAPI async)

**History storage:** In-memory (limited to 100 records by default)

## Security Considerations

### Wi-Fi Network

- **Default password:** "rocktimer" (change in setup script)
- **WPA2-PSK encryption**
- **No internet gateway** (isolated network)

### Web UI

- **No authentication** (local network only)
- **No HTTPS** (not needed on isolated network)
- **No user accounts** (single-user system)

### GPIO Access

- **Requires root** (both server and sensors run as root)
- **Risk:** Code execution = full system access
- **Mitigation:** Read-only root filesystem (optional)

## Extensibility

### Alternative Displays

Replace touchscreen with:
- **Phone/tablet:** Connect to rocktimer Wi-Fi, open browser
- **Apple Watch:** Use companion app (see `apple-watch/`)

## Testing

### Unit Tests

**TODO:** Add pytest tests for:
- State machine transitions
- Time calculations
- UDP message parsing
- WebSocket protocol

### Integration Tests

**Simulate full system:**
```bash
python tools/simulate_triggers.py --simulate --loop 10
```

**Test specific scenarios:**
```bash
# Stone that doesn't reach far hog
python tools/simulate_triggers.py --simulate --skip-far

# Very fast stone
python tools/simulate_triggers.py --simulate --tee-hog 2.5 --hog-hog 8.0

# Very slow stone
python tools/simulate_triggers.py --simulate --tee-hog 3.5 --hog-hog 15.0
```

### Hardware Tests

**Sensor test (on each Pi):**
```bash
sudo python /opt/rocktimer/tools/test_sensor.py
```

**Time sync test:**
```bash
# On all Pi's, check offset
chronyc tracking | grep "System time"
# Should be < 1ms
```

## Troubleshooting Tools

### Logs

```bash
# Server
sudo journalctl -u rocktimer-server -f

# Sensor
sudo journalctl -u rocktimer-sensor -f

# Kiosk
sudo journalctl -u rocktimer-kiosk -f

# TTS
tail -f /var/log/rocktimer-tts.log
```

### Network Debugging

```bash
# Check Wi-Fi AP
systemctl status hostapd

# Check DHCP
systemctl status dnsmasq

# See connected clients
cat /var/lib/misc/dnsmasq.leases

# Test UDP send (from Pi Zero to Pi 4)
echo '{"type":"trigger","device_id":"test","timestamp_ns":1234567890}' | nc -u 192.168.50.1 5000

# Monitor UDP traffic
sudo tcpdump -i wlan0 -n port 5000
```

### GPIO Debugging

```bash
# Test GPIO (manual trigger)
sudo python /opt/rocktimer/tools/test_sensor.py

# Check GPIO state
gpio readall  # If gpio command is installed
```


---

**For questions or contributions, see the main README.md**

