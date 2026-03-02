# Stone Timer - Curling Timing System

Stone Timer is a DIY curling stone timing system that measures split times between the **tee line**, the **near hog line**, and the **far hog line** using simple laser trip sensors.

**Perfect for:** Practice sessions, coaching, analyzing stone speed and release consistency

## Key Features

- ⏱️ **Accurate timing** between three trigger points (tee alt. backline, near hog, far hog)
- 📱 **Touch-friendly UI** optimized for 5" displays (also works on phones/tablets)
- 🔊 **Voice announcements** (optional) - speaks times using Piper TTS
- 🌐 **Local Wi-Fi** - no internet required, Pi 4 creates its own network
- 📊 **History tracking** - review previous measurements
- ⚡ **Fast response** - WebSocket updates, instant feedback
- 🔌 **Simple hardware** - laser modules + LM393 sensors + Raspberry Pi

## System Overview

It is designed for a **3‑Pi setup**:
- **Pi 4 (server at near hog line)**: runs the central server + touchscreen UI + optional voice announcements
- **2× Pi Zero 2 W (tee + far hog)**: read sensors and send trigger timestamps over UDP

**Credit:** Inspired by Larry Ehnert's LarryRockTimer (`LarryRockTimer.com`).

## Quick Start Summary

1. **Get hardware** (see Bill of Materials below): 1× Pi 4, 2× Pi Zero 2 W, 3× laser modules, 3× LM393 sensors
2. **Install OS** on all three Pi's (Raspberry Pi OS Lite or Desktop)
3. **Run installers:**
   - Pi 4: `sudo ./install_server.sh` (sets up server + kiosk + Wi-Fi AP)
   - Pi Zero: `sudo ./install_sensor.sh` (choose tee or hog_far)
4. **Wire sensors** (see Wiring Diagrams below)
5. **Test:** Open http://192.168.50.1:8080 and break the laser beams

**Estimated build time:** 2-4 hours (first time, including OS installation)

## Documentation

- **[QUICKSTART.md](QUICKSTART.md)** - Step-by-step guide to build your first Stone Timer (recommended for beginners)
- **[ARCHITECTURE.md](ARCHITECTURE.md)** - Technical deep-dive: system design, protocols, data flow
- **README.md** (this file) - Complete reference guide

## Overview

```
   TEE LINE              HOG LINE (near)         HOG LINE (far)
      │                        │                        │
   [Sensor]                [Sensor]                 [Sensor]
   Pi Zero  ──UDP:5000──►   Pi 4   ◄──UDP:5000──  Pi Zero
                              │
                         Web UI :8080
```

Sensors send triggers to the server. The server ignores them unless the system is armed.

## Quickstart (fresh Raspberry Pi OS)

Below are the “from zero” steps for a brand new Raspberry Pi OS installation.

### Pi 4 (Server + kiosk display)

**Prerequisites**
- Raspberry Pi OS installed (Bookworm/Bullseye), SSH enabled
- (Recommended) Pi 4 acts as the Stone Timer **Wi‑Fi AP**

**1) Clone and install**

```bash
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/jbevemyr/stonetimer.git
cd stonetimer

# Installs server + kiosk (Chromium fullscreen) + dependencies
sudo ./install_server.sh
```

**2) (Recommended) Set up Stone Timer Wi‑Fi (AP)**

```bash
sudo ./setup/setup_network.sh
sudo reboot
```

After reboot:
- The server IP is typically **`192.168.50.1`**
- Web UI: **`http://192.168.50.1:8080`** (or `http://stonetimer` if you also set up DNS/port 80)

**3) Start / check status**

```bash
sudo systemctl enable --now stonetimer-server.service stonetimer-kiosk.service
systemctl status stonetimer-server.service stonetimer-kiosk.service --no-pager
```

**4) (Optional) Chrony from the installer**

To skip prompts:

```bash
sudo STONETIMER_CONFIGURE_CHRONY=1 ./install_server.sh
```

### Pi Zero 2 W (Sensor: tee or hog_far)

**Prerequisites**
- Raspberry Pi OS installed
- Wi‑Fi preconfigured to join the StoneTimer SSID (default `stonetimer`)
- SSH enabled (so you can run the installer remotely)

**1) Clone and install**

```bash
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/jbevemyr/stonetimer.git
cd stonetimer

# Choose tee or hog_far when prompted
sudo ./install_sensor.sh
```

**2) Point the sensor at the Pi 4**

Verify in `/opt/stonetimer/config.yaml` that the server points to the Pi 4:

- `host: "192.168.50.1"`

**3) Start / check status**

```bash
sudo systemctl enable --now stonetimer-sensor.service
systemctl status stonetimer-sensor.service --no-pager
```

**4) (Optional) Chrony from the installer**

```bash
sudo STONETIMER_CONFIGURE_CHRONY=1 STONETIMER_CHRONY_SERVER=192.168.50.1 ./install_sensor.sh
```

## Network (Pi 4 as Wi‑Fi Access Point)

Stone Timer is designed to run on a **local Wi‑Fi network** created by the Pi 4:

- **Pi 4**: runs the server + acts as a **Wi‑Fi Access Point** (AP), typically `192.168.50.1`
- **Pi Zero 2 W** units: connect to the Pi 4 Wi‑Fi and send UDP triggers to the server

This repo includes a helper script to configure the AP on the Pi 4:

```bash
sudo ./setup/setup_network.sh
```

After running it:
- Connect your **Pi Zero 2 W** devices to the SSID shown by the script (default `stonetimer`)
- Verify they get an IP in the `192.168.50.x` range
- Ensure the server IP in the sensor config is set to the Pi 4 address (e.g. `192.168.50.1`)

### Viewing times from a phone

If you have a phone/tablet, you can join the Stone Timer Wi‑Fi network and open:

- `http://192.168.50.1` (or `http://192.168.50.1:8080`)

This lets you view live times from your phone and press **Rearm** without using the touchscreen.

### No touchscreen required

The touchscreen is optional. You can build Stone Timer without a display and rely on:

- A **phone/tablet** connected to the Stone Timer Wi‑Fi network
- An **Apple Watch / iOS** companion app (see `StoneTimer/`)
- Any **laptop/desktop** on the same Wi‑Fi network using a web browser

### Local hostname: http://stonetimer

If you use the provided Wi‑Fi AP setup, dnsmasq can be configured to resolve:

- `stonetimer` → `192.168.50.1`

So you can type `http://stonetimer` in your browser.

Note: Stone Timer itself runs on **port 8080** by default. If you want plain port **80**,
use the optional Nginx reverse proxy setup:

```bash
sudo ./setup/setup_nginx_proxy.sh
```

### Phones complaining about "No Internet" (optional)

If the Pi 4 Wi‑Fi network has no upstream internet (common for Stone Timer), phones may show a warning like
“No internet” and sometimes try to switch away from Wi‑Fi.

Stone Timer can reduce this annoyance by answering common captive-portal / connectivity checks locally:

- `setup/setup_network.sh` adds dnsmasq rules that map those check domains to the Pi 4 IP
- `setup/setup_nginx_proxy.sh` (port 80) returns the expected small responses (204/Success/text)

If you already set up the AP and/or nginx earlier, re-run the scripts after pulling updates:

```bash
sudo ./setup/setup_network.sh
sudo ./setup/setup_nginx_proxy.sh
sudo reboot
```

## Boot splash screen (optional)

If you want a simple boot splash during OS startup that shows:

- Stone Timer
- **jb@bevemyr.com**

…you can enable a custom Plymouth theme:

```bash
sudo ./setup/setup_splash.sh
```

You can also override the text:

```bash
sudo ./setup/setup_splash.sh "Stone Timer" "jb@bevemyr.com"
```

This uses Plymouth and generates a simple image-based splash (curling stone + text). If you use a different display resolution than the Pi 7" touchscreen, re-run the script after switching displays so it can regenerate the image at the detected resolution.

### Apple Watch & iOS

The repository also contains an iOS and Apple Watch companion app under `StoneTimer/` (Xcode project). It displays StoneTimer times and supports arm/rearm from phone or watch.

## Time sync (Chrony)

Accurate timing requires the clocks on all devices to be synchronized.
Use **chrony** with the Pi 4 as the local time server.

### Quick setup via install scripts (recommended)

Both install scripts can optionally configure chrony for you (idempotent: re-running updates the Stone Timer block).

- **Pi 4 (server)**:

```bash
sudo STONETIMER_CONFIGURE_CHRONY=1 ./install_server.sh
```

Optional overrides:

```bash
sudo STONETIMER_CONFIGURE_CHRONY=1 STONETIMER_CHRONY_CIDR=192.168.50.0/24 ./install_server.sh
```

- **Pi Zero 2 W (sensor/client)**:

```bash
sudo STONETIMER_CONFIGURE_CHRONY=1 STONETIMER_CHRONY_SERVER=192.168.50.1 ./install_sensor.sh
```

#### Faster “correct time” after long power-off (makestep)

By default, the install scripts add:

- `makestep 1.0 3`

Meaning: if the clock differs by more than **1 second**, chrony is allowed to **step** to the correct time during the first **3** updates after boot. This helps Pi Zero clients get “correct” quickly even if they have been powered off for a long time.

You can change this:

```bash
sudo STONETIMER_CONFIGURE_CHRONY=1 STONETIMER_CHRONY_MAKESTEP_THRESHOLD=0.5 STONETIMER_CHRONY_MAKESTEP_LIMIT=5 ./install_sensor.sh
```

If you don't set `STONETIMER_CONFIGURE_CHRONY`, the installer will prompt you.

### 1) Install chrony

On all Pi’s:

```bash
sudo apt-get update
sudo apt-get install -y chrony
```

### 2) Pi 4 (server) configuration

Edit `/etc/chrony/chrony.conf` on the Pi 4 and add something like:

```conf
# Allow LAN clients (Stone Timer Wi‑Fi network)
allow 192.168.50.0/24

# Optional: keep stable even without internet
local stratum 10
```

Restart:

```bash
sudo systemctl restart chrony
```

### 3) Pi Zero 2 W (clients) configuration

Edit `/etc/chrony/chrony.conf` on each Pi Zero and add:

```conf
# Use the Pi 4 as the time source
server 192.168.50.1 iburst prefer
```

Restart:

```bash
sudo systemctl restart chrony
```

### 4) Verify sync

On clients:

```bash
chronyc tracking
chronyc sources -v
```

You should see the Pi 4 (`192.168.50.1`) as the preferred source and a small offset.

### Example config files

Copy-ready examples are available in:
- `setup/chrony-server.conf`
- `setup/chrony-client.conf`

## Installation

### Pi 4 (Server)
```bash
sudo ./install_server.sh
```

### Pi Zero 2 W (Sensors)
```bash
sudo ./install_sensor.sh
# Choose: tee or hog_far
```

## Updating / Upgrading

Stone Timer is installed to **`/opt/stonetimer`** and runs via systemd services. You can safely re-run the installers to apply updates.

### Recommended update flow (Pi 4 + Pi Zero)

1) **Backup your config**

```bash
sudo cp -a /opt/stonetimer/config.yaml /opt/stonetimer/config.yaml.bak.$(date -Is)
```

2) **Update code**

If `/opt/stonetimer` contains a git checkout (it usually does after installation):

```bash
cd /opt/stonetimer
sudo git pull
```

Otherwise, pull updates on your laptop and re-run the installer from the cloned repo.

3) **Re-run installer (idempotent)**

- Pi 4:

```bash
cd /opt/stonetimer
sudo ./install_server.sh
sudo systemctl restart stonetimer-server.service
```

- Pi Zero:

```bash
cd /opt/stonetimer
sudo ./install_sensor.sh
sudo systemctl restart stonetimer-sensor.service
```

## Configuration

Sensors only need to know the server IP:

```yaml
# configs/config-zero-tee.yaml
device_id: "tee"
server:
  host: "192.168.50.1"
  port: 5000
```

## Hardware

If you want to build your own Stone Timer setup, this is the hardware used in this project.

### Bill of Materials (BOM)

**Complete shopping list for one Stone Timer system:**

#### Compute Units
- 1× Raspberry Pi 4 Model B (4GB or 8GB recommended)
- 2× Raspberry Pi Zero 2 W
- 3× MicroSD cards (32GB+ recommended, Class 10 or better)
- 3× Power banks (Pi 4: 10000mAh+, Pi Zero: 5000mAh+)
- 3× USB cables for power (USB-C for Pi 4, Micro-USB for Pi Zero)

#### Display (Optional, but recommended for Pi 4)
- 1× Elecrow RC050 5-inch HDMI capacitive touch LCD (800×480)
  - Alternative: Any HDMI touchscreen or regular display
  - Or: Use phone/tablet instead via Wi-Fi

#### Sensors (3 trigger points: tee, hog_close, hog_far)
- 3× LM393 light sensor modules
- 1× IR proximity sensor module (for arm trigger on Pi 4)

#### Laser Modules
- 3× Red dot laser heads (3–5V, 650nm, 5mW, 6mm diameter)
- 3× Battery holders with switch (3× AA, 4.5V output)
- 9× AA batteries (3 per holder)

#### Audio (Optional - for voice announcements)
- 1× PAM8403 or HW-104 amplifier module
- 1× Speaker (3W, 4–8Ω, ~40mm diameter)
- 1× B103 potentiometer (10kΩ) for volume control
- 1× 3.5mm audio cable

#### Electronics & Wiring
- Dupont jumper wires (male-female, female-female)
- Heat-shrink tubing
- Optional: project boxes/enclosures


### Placement on the ice (practical build notes)

- **Sensor locations**:
  - **Tee**: on the tee line, or on the back line if you prefer to time from there
  - **Hog close**: near hog line (this is the Pi 4 location)
  - **Hog far**: far hog line
- **Laser + receiver**: mount **opposite** each other across the sheet so the beam crosses the stone path.
- **Height**: aim the beam so it reliably breaks on a passing stone but does not clip brooms/feet (you may need to experiment).
- **Alignment**: start by aligning the laser to the receiver at close distance, then move out to full width and fine-tune.
- **Stability**: small movements matter; use rigid brackets and avoid “floppy” stands.
- **Safety**: use low-power laser modules and avoid pointing at eyes; confirm local rules for your facility.

### Compute + Display
- **1× Raspberry Pi 4 Model B** (central server at the near hog line)
- **2× Raspberry Pi Zero 2 W** (remote sensors: tee line + far hog line)
- **1× Touch display**: Elecrow **RC050** 5-inch HDMI capacitive touch LCD (800×480)

### Sensors (3 trigger points)
- **3× Light sensor modules** (LM393-style “laser trip” sensors), one per line:
  - Tee line (Pi Zero 2 W)
  - Near hog line (Pi 4)
  - Far hog line (Pi Zero 2 W)
- **1× IR proximity sensor module** (used on the Pi 4 as an “arm” trigger)

### Lasers (one per trigger point)
- **3× Red dot laser heads** (3–5V, 650nm, 5mW, 6mm diameter)  
- **3× Battery holders with switch** (one per laser), e.g.:
  - “3 AA Battery Holder with Cover and Switch” (4.5V)

### Power
- **3× Power banks** (one per Raspberry Pi)
  - Pick capacity based on expected runtime; a Pi 4 typically needs a larger bank than a Zero 2 W.

### Audio (for voice announcements)
- **1× Small amplifier module** (e.g. PAM8403 / HW-104)
- **1× Speaker** (recommended: **3W**, **4–8Ω**, small form factor ~40mm)
- **1× Potentiometer for volume**: **B103 (10kΩ)** (thumbwheel or trimmer)
- **1× 3.5mm audio cable** (Pi 4 headphone jack → amplifier input)

### Wiring / mounting (recommended)
- Jumper wires / Dupont cables, screw terminals, heat-shrink, etc.
- Mounting hardware for sensors + lasers (brackets/holders) to keep alignment stable.

### Wiring Diagrams

#### Timing sensor (LM393 - all Pi's)

Connect the LM393 light sensor to GPIO 17 on all three Raspberry Pi units:

```
LM393 Light Sensor    →    Raspberry Pi (all units)
──────────────────────────────────────────────────
VCC (power)           →    Pin 1  (3.3V)
GND (ground)          →    Pin 6  (GND)
DO  (digital out)     →    Pin 11 (GPIO 17)
```

**Pin layout reference (looking at GPIO header, USB ports facing down):**
```
     3.3V [1] [2]  5V
          [3] [4]  5V
          [5] [6]  GND  ← GND
          [7] [8]
      GND [9] [10]
 GPIO 17 [11] [12]     ← GPIO 17 (DO)
          ↑
```

**Notes:**
- The LM393 module typically has a potentiometer to adjust trigger sensitivity
- Test the sensor: the onboard LED should light when the laser beam is broken
- Adjust the potentiometer until it reliably triggers on beam break but not on ambient light

#### Arm sensor (IR proximity - Pi 4 only)

The IR sensor is used to arm the system by waving your hand in front of it:

```
IR Proximity Sensor   →    Raspberry Pi 4
──────────────────────────────────────────
VCC (power)           →    Pin 17 (3.3V)
GND (ground)          →    Pin 14 (GND)
DO  (digital out)     →    Pin 13 (GPIO 27)
```

**Usage:** Hold your hand ~5cm in front of the IR sensor to arm the system. The sensor typically has a range adjustment - set it to 5-10cm for best results.

#### Complete system wiring (Pi 4 with all sensors + audio)

```
┌─────────────────────────────────────────────────────┐
│                  Raspberry Pi 4                      │
│                                                      │
│  [GPIO Header]         [Audio Jack]    [HDMI]       │
│   │ │ │ │ │               │              │          │
└───┼─┼─┼─┼─┼───────────────┼──────────────┼──────────┘
    │ │ │ │ │               │              │
    │ │ │ │ │               │         [Touchscreen]
    │ │ │ │ │               │
    │ │ │ │ │               └─────[Volume pot]──[Amplifier]──[Speaker]
    │ │ │ │ │
    │ │ │ │ └─── IR Sensor (GPIO 27, arm trigger)
    │ │ │ └───── GND
    │ │ └─────── LM393 Sensor (GPIO 17, hog_close timing)
    │ └───────── GND
    └─────────── 3.3V (power for both sensors)
```

### Bring-up checklist (first successful run)

- **Server up**:
  - `systemctl status stonetimer-server.service --no-pager`
  - Open UI: `http://<pi4-ip>:8080`
- **Sensors up**:
  - `systemctl status stonetimer-sensor.service --no-pager`
  - Watch logs while breaking the beam: `sudo journalctl -u stonetimer-sensor -f`
- **End-to-end test without hardware (UDP simulation)**:

```bash
python tools/simulate_triggers.py --server 127.0.0.1 --simulate
```

### Audio - Amplifier and speaker (Pi 4)

The system can announce times using text-to-speech. Use a small amplifier module (e.g. HW-104/PAM8403)
and a 3W speaker for an enclosure build.

Stone Timer uses **Piper (Coqui TTS)** for speech. The server calls `/opt/piper/speak.sh`, which pipes Piper audio to `/usr/bin/aplay`.

#### Faster callouts (optional)

On Raspberry Pi, launching Piper for every callout can add noticeable latency (model load + synthesis).
The installer pre-generates small audio fragments for `0-9` and `point` and the TTS helper can stitch
them together for phrases like `3 point 1 8`.

It also caches a few short phrases (e.g. `ready to go`) so they play without model load time.

To force the fast path, set:

```bash
STONETIMER_TTS_FAST=1
```

You can also tune Piper speech speed and the pause between digits:

```bash
# Faster speech (lower is faster). Default: 0.75
STONETIMER_PIPER_LENGTH_SCALE=0.75

# Silence after each sentence (seconds). Default: 0.0
STONETIMER_PIPER_SENTENCE_SILENCE=0.0

# Pause between tokens in the stitched digit callouts (ms). Default: 20
STONETIMER_TTS_TOKEN_PAUSE_MS=20
```

**Parts:**
- HW-104 or PAM8403 amplifier module
- B103 potentiometer (10kΩ) for volume control
- 3W speaker (4-8Ω, ~40mm)
- 3.5mm audio cable

**Wiring with volume control:**
```
Pi 4                          B103 Potentiometer
────                          ──────────────────
3.5mm TIP (audio) ─────────►  Pin 1 (input)
3.5mm SLEEVE (GND) ────────►  Ben 3 (GND)
                              Pin 2 (output) ───┐
                                                │
                              HW-104 Amplifier  │
                              ──────────────────┘
Pi 5V (pin 2) ─────────────►  VCC
Pi GND (pin 6) ────────────►  GND
Potentiometer pin 2 ───────►  L-IN
Potentiometer pin 3 ───────►  GND (common)
                              L+ ──────────────► Speaker +
                              L- ──────────────► Speaker -
```

**Diagram:**
```
┌─────────┐      ┌──────────────┐      ┌────────┐      ┌──────────┐
│  Pi 4   │      │ Potentiometer│      │ HW-104 │      │ Speaker  │
│         │      │    B103      │      │        │      │   3W     │
│  3.5mm ─┼──1───┤►             │      │        │      │          │
│   jack  │      │       2──────┼──────┤► L-IN  │      │          │
│    GND ─┼──────┤► 3           │      │        │      │          │
│         │      └──────────────┘      │   L+ ──┼──────┤► +       │
│   5V ───┼────────────────────────────┤► VCC   │      │          │
│   GND ──┼────────────────────────────┤► GND   │      │          │
│         │                            │   L- ──┼──────┤► -       │
└─────────┘                            └────────┘      └──────────┘
```

**Enable analog audio output:**
```bash
sudo raspi-config
# System Options → Audio → Headphones

# Or directly:
amixer cset numid=3 1

# IMPORTANT: the server runs as root (for GPIO), so test audio as root too:
sudo aplay -D hw:0,0 /usr/share/sounds/alsa/Front_Center.wav

# Test Piper (Coqui TTS via piper binary):
# NOTE: ALSA card numbers can change across reboots, so avoid hardcoding plughw:X,Y unless you know the correct device.
echo "ready to go" | /opt/piper/piper --model /opt/piper/voices/en_US-lessac-medium.onnx --output-raw | /usr/bin/aplay -r 22050 -f S16_LE -c 1 -D default

# Or test via the helper script used by the server:
/opt/piper/speak.sh "ready to go"

# If you get sound as your user but NOT from the server, try forcing an ALSA device that supports mixing:
# (These names depend on your `aplay -L` output)
ALSA_DEVICE="default:CARD=Headphones" /opt/piper/speak.sh "ready to go"
ALSA_DEVICE="dmix:CARD=Headphones,DEV=0" /opt/piper/speak.sh "ready to go"
```

## Test

```bash
# Simulate a stone pass
python tools/simulate_triggers.py --simulate

# Single trigger
python tools/simulate_triggers.py --device tee

# Simulate 5 stones in a row (useful for testing)
python tools/simulate_triggers.py --simulate --loop 5

# Test sensor hardware directly (on Pi Zero or Pi 4)
sudo python tools/test_sensor.py
```

## Troubleshooting

### Server won't start

**Symptoms:** `systemctl status stonetimer-server` shows failed/error

**Solutions:**
```bash
# Check logs for error details
sudo journalctl -u stonetimer-server -n 50

# Common issues:
# 1. Port 8080 already in use - change http_port in config.yaml
# 2. Config file missing or invalid - verify /opt/stonetimer/config.yaml exists
# 3. Python dependencies missing - re-run install_server.sh

# Test server manually to see errors directly
cd /opt/stonetimer
sudo venv/bin/python server/main.py
```

### Sensors not triggering

**Symptoms:** Breaking the laser beam doesn't register on the server

**Solutions:**
```bash
# 1. Test the sensor locally (on the Pi with the sensor)
sudo python /opt/stonetimer/tools/test_sensor.py
# This should print "TRIGGER!" when you break the beam

# 2. Check sensor wiring
# - VCC → 3.3V (NOT 5V, it can damage the Pi!)
# - GND → GND
# - DO → GPIO 17

# 3. Verify sensor logs
sudo journalctl -u stonetimer-sensor -f
# You should see "TRIGGER! tee" (or hog_far) when breaking beam

# 4. Check network connectivity (for Pi Zero sensors)
ping 192.168.50.1  # Should respond if connected to Pi 4 Wi-Fi

# 5. Test UDP manually from Pi Zero to Pi 4
echo '{"type":"trigger","device_id":"tee","timestamp_ns":1234567890}' | nc -u 192.168.50.1 5000
```

### No voice announcements

**Symptoms:** Times display correctly but no audio

**Solutions:**
```bash
# 1. Check if speech is enabled in Settings (via web UI)

# 2. Test audio output as root (server runs as root)
sudo aplay /usr/share/sounds/alsa/Front_Center.wav

# 3. Force analog audio jack (if using Pi 4 headphone output)
sudo amixer cset numid=3 1

# 4. Test Piper TTS directly
sudo /opt/piper/speak.sh "ready to go"

# 5. Check TTS logs
sudo tail -f /var/log/stonetimer-tts.log

# 6. Verify speaker wiring (see audio diagram in Hardware section)
```

### Touchscreen not working (kiosk mode)

**Symptoms:** Display shows Chromium but touch doesn't work

**Solutions:**
```bash
# 1. Check if kiosk service is running
systemctl status stonetimer-kiosk

# 2. Test touch in terminal
# Install evtest: sudo apt-get install evtest
sudo evtest
# Select the touch device and tap the screen

# 3. Chromium may need touch calibration
# Add this to /boot/firmware/config.txt (or /boot/config.txt on older systems):
# dtoverlay=rpi-ft5406  # For official Pi touchscreen
# Reboot after editing

# 4. Manual test (stop kiosk first)
sudo systemctl stop stonetimer-kiosk
export DISPLAY=:0
chromium --kiosk http://localhost:8080
```

### Time synchronization issues

**Symptoms:** Measurements show impossible times or negative values

**Solutions:**
```bash
# 1. Check chrony sync status on all Pi's
chronyc tracking
chronyc sources -v

# 2. On Pi Zero, verify it's syncing to Pi 4
chronyc sources -v
# Should show 192.168.50.1 with '*' or '=' (selected source)

# 3. Force time sync (on Pi Zero)
sudo systemctl restart chrony
# Wait 10 seconds
chronyc tracking
# "System time" offset should be < 1ms

# 4. If Pi 4 has no internet and shows wrong time
# Manually set time on Pi 4 (it will then serve as time source for sensors)
sudo date -s "2024-12-22 15:30:00"
sudo systemctl restart chrony
```

### Network issues (Pi 4 as AP)

**Symptoms:** Pi Zero can't connect to stonetimer Wi-Fi

**Solutions:**
```bash
# 1. Verify AP is running on Pi 4
sudo systemctl status hostapd
sudo systemctl status dnsmasq

# 2. Check if wlan0 has the correct IP
ip addr show wlan0
# Should show 192.168.50.1

# 3. Restart network services
sudo systemctl restart dhcpcd
sudo systemctl restart hostapd
sudo systemctl restart dnsmasq

# 4. Check for Wi-Fi interference
# Change channel in /etc/hostapd/hostapd.conf
# Replace: channel=7
# With: channel=1 or channel=11
sudo systemctl restart hostapd

# 5. Verify Pi Zero Wi-Fi config
# On Pi Zero, edit /etc/wpa_supplicant/wpa_supplicant.conf
# Both SSIDs so the Pi Zero works during migration from rocktimer -> stonetimer
network={
    ssid="stonetimer"
    psk="stonetimer"
    key_mgmt=WPA-PSK
}
network={
    ssid="rocktimer"
    psk="rocktimer"
    key_mgmt=WPA-PSK
}
```

### Web UI shows old data or won't update

**Symptoms:** Times don't update in real-time

**Solutions:**
```bash
# 1. Check WebSocket connection in browser console (F12)
# Should see: "WebSocket connected"

# 2. Hard refresh the page
# Chrome/Edge: Ctrl+Shift+R
# Firefox: Ctrl+F5

# 3. Clear browser cache
# Settings → Privacy → Clear browsing data

# 4. Test from different device
# Connect phone to stonetimer Wi-Fi
# Open: http://192.168.50.1:8080
```

### General debugging

```bash
# View all logs
sudo journalctl -u stonetimer-server -f    # Server (Pi 4)
sudo journalctl -u stonetimer-sensor -f    # Sensor (Pi Zero)
sudo journalctl -u stonetimer-kiosk -f     # Kiosk display (Pi 4)

# Check system resources
htop

# Verify Python dependencies
cd /opt/stonetimer
source venv/bin/activate
pip list

# Full reinstall (last resort)
cd /opt/stonetimer
sudo ./install_server.sh  # or install_sensor.sh
```

## API

### POST /api/arm
Arm the system.
```json
{"success": true, "state": "armed"}
```

### POST /api/disarm
Cancel the current measurement.
```json
{"success": true, "state": "idle"}
```

### GET /api/status
Get current status.
```json
{
  "state": "completed",
  "session": {
    "tee_time_ns": 1702312345678901234,
    "hog_close_time_ns": 1702312348778901234,
    "hog_far_time_ns": 1702312359078901234,
    "tee_to_hog_close_ms": 3100.0,
    "hog_to_hog_ms": 10300.0,
    "total_ms": 13400.0,
    "has_hog_close": true,
    "has_hog_far": true,
    "started_at": "2024-12-11T18:52:25.678901"
  },
  "sensors": {}
}
```

### GET /api/times
Get history (latest measurements).
```json
[
  {
    "id": 1,
    "timestamp": "2024-12-11T18:52:25.678901",
    "tee_to_hog_close_ms": 3100.0,
    "hog_to_hog_ms": 10300.0,
    "total_ms": 13400.0
  }
]
```

### GET /api/current
Get current measurement (same as session in status).
```json
{
  "tee_to_hog_close_ms": 3100.0,
  "hog_to_hog_ms": null,
  "total_ms": null,
  "has_hog_close": true,
  "has_hog_far": false
}
```

### WebSocket /ws
Real-time updates. Connect and receive `state_update` messages:
```json
{"type": "state_update", "data": {"state": "armed", "session": {...}}}
```

Send commands:
```json
{"type": "arm"}
{"type": "disarm"}
```
