# RockTimer Quick Start Guide

This guide will get you from zero to a working RockTimer system in ~3 hours.

## Prerequisites

- 1× Raspberry Pi 4 (4GB+ recommended)
- 2× Raspberry Pi Zero 2 W
- 3× MicroSD cards (32GB+, Class 10 or better)
- 3× Laser modules + LM393 sensors (see hardware list in README)
- Basic soldering/wiring skills
- Access to a curling sheet

## Step-by-Step Setup

### Phase 1: Operating System (30 minutes)

1. **Download Raspberry Pi OS**
   - Get "Raspberry Pi OS Lite" (64-bit) for Pi Zero
   - Get "Raspberry Pi OS with desktop" (64-bit) for Pi 4 (if using touchscreen)
   - Use Raspberry Pi Imager: https://www.raspberrypi.com/software/

2. **Flash all three SD cards**
   - Pi 4: Desktop version
   - 2× Pi Zero: Lite version
   - Enable SSH during imaging (in Imager settings)
   - Set username/password (e.g., pi/rocktimer)

3. **Initial boot and SSH access**
   ```bash
   # Find Pi IP addresses on your network
   sudo nmap -sn 192.168.1.0/24
   
   # SSH into each Pi
   ssh pi@192.168.1.XXX
   
   # Update system
   sudo apt-get update
   sudo apt-get upgrade -y
   ```

### Phase 2: Software Installation (45 minutes)

#### Pi 4 (Server)

```bash
# Install git
sudo apt-get install -y git

# Clone repository
git clone https://github.com/jbevemyr/rocktimer.git
cd rocktimer

# Run installer (sets up server + kiosk + Wi-Fi AP + time sync)
sudo ./install_server.sh
# Note: first run can take a few minutes. It downloads Piper TTS + voice model and
# generates a cache of small audio fragments under /opt/piper/cache for fast callouts.
# Re-runs are much faster.
# Answer "Y" when asked about chrony

# Start services now (optional, but recommended so you can verify everything works)
sudo systemctl start rocktimer-server

# Enable + start kiosk mode (recommended if using a Pi 4 touchscreen)
# "enable" makes it start automatically on boot.
sudo systemctl enable rocktimer-kiosk
sudo systemctl start rocktimer-kiosk

# Optional: add a boot splash screen (Plymouth)
# Reboot is required to see it.
sudo ./setup/setup_splash.sh

# Set up Wi-Fi Access Point
sudo ./setup/setup_network.sh
# Note: this also enables internet sharing (NAT) by default so Pi Zero clients can reach the internet
# via the Pi 4 uplink (typically eth0). To disable:
# sudo ROCKTIMER_ENABLE_INTERNET_SHARING=0 ./setup/setup_network.sh

# Quick verification (no reboot needed just to test):
# ip -brief addr show wlan0   # should show 192.168.50.1/24
# systemctl status hostapd dnsmasq --no-pager

# Reboot to activate Wi-Fi AP
sudo reboot
```

After reboot:
- Pi 4 should create Wi-Fi network "rocktimer" (password: "rocktimer")
- Pi 4 IP should be 192.168.50.1

#### Pi Zero #1 (Tee sensor)

```bash
# Connect Pi Zero to your regular Wi-Fi first (for installation)
# After setup, configure it to connect to "rocktimer" Wi-Fi

sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/jbevemyr/rocktimer.git
cd rocktimer

# Run installer and select "tee" when prompted
sudo ./install_sensor.sh
# Choose option 1 (tee)
# Answer "Y" for chrony, use default server 192.168.50.1
```

Configure Wi-Fi to connect to Pi 4:
```bash
sudo nano /etc/wpa_supplicant/wpa_supplicant.conf
```

Add:
```
network={
    ssid="rocktimer"
    psk="rocktimer"
    priority=10
}
```

Reboot:
```bash
sudo reboot
```

#### Pi Zero #2 (Far hog sensor)

Same as Pi Zero #1, but choose option 2 (hog_far) during installation.

### Phase 3: Hardware Assembly (60-90 minutes)

#### 1. Wire the sensors

**On each Pi (including Pi 4), connect LM393 sensor:**
```
LM393 → Raspberry Pi
VCC → Pin 1 (3.3V)
GND → Pin 6 (GND)
DO  → Pin 11 (GPIO 17)
```

**On Pi 4 only, also connect IR sensor:**
```
IR Sensor → Raspberry Pi 4
VCC → Pin 17 (3.3V)
GND → Pin 14 (GND)
DO  → Pin 13 (GPIO 27)
```

#### 2. Set up lasers

- Place laser modules opposite the sensors across the sheet
- Align laser beam to hit the LM393 sensor photoresistor
- Secure everything (clamps, tape, weights)
- Power lasers with 3× AA batteries (4.5V)

#### 3. Adjust sensor sensitivity

Each LM393 module has a potentiometer:
- Turn it until the onboard LED turns ON when laser hits the sensor
- LED should turn OFF when beam is broken
- Test by blocking the beam with your hand

### Phase 4: Testing (15 minutes)

#### 1. Check all services are running

**On Pi 4:**
```bash
# SSH to Pi 4 (connect to rocktimer Wi-Fi, then ssh pi@192.168.50.1)
systemctl status rocktimer-server --no-pager
systemctl status rocktimer-kiosk --no-pager
```

**On each Pi Zero:**
```bash
# SSH to Pi Zero via Pi 4 (find IP: sudo nmap -sn 192.168.50.0/24)
systemctl status rocktimer-sensor --no-pager
```

#### 2. Test web UI

On your phone/laptop, connect to "rocktimer" Wi-Fi and open:
- http://192.168.50.1:8080

You should see the RockTimer interface with two time cards.

#### Sensor status indicators (Pi 4 UI)

In the top bar of the UI you will see small dots for the remote sensors (Tee / Hog far).
- **Green**: sensor is alive (heartbeat/triggers seen recently)
- **Red**: sensor appears offline

#### 3. Test sensors manually

**On each Pi Zero:**
```bash
sudo journalctl -u rocktimer-sensor -f
```

Block the laser beam - you should see:
```
TRIGGER! tee
```

**On Pi 4, check server receives triggers:**
```bash
sudo journalctl -u rocktimer-server -f
```

When you break a beam, you should see:
```
Trigger: tee (or hog_close, or hog_far)
```

#### 4. Simulate a stone pass

```bash
cd /opt/rocktimer
python tools/simulate_triggers.py --simulate
```

This sends fake triggers in sequence. Check the web UI - it should show times.

### Phase 5: On-Ice Setup (30 minutes)

#### Positioning

```
[House]          [FAR HOG LINE]      [NEAR HOG LINE]      [TEE LINE]
                      │                    │                   │
                  [Pi Zero 2]          [Pi 4]            [Pi Zero 1]
                  [Laser ←→ Sensor]   [Laser ←→ Sensor] [Laser ←→ Sensor]
```

**Important:**
- Place sensors on ONE side of the sheet
- Place lasers on the OPPOSITE side
- Align beams perpendicular to stone path
- Height: ~8-12cm (low enough to catch stone, high enough to avoid brooms/feet)

#### Power

- Use power banks to power all Pi units
- Keep lasers powered separately (3× AA batteries per laser)

#### Final test

1. Wave hand in front of IR sensor on Pi 4 to arm system
2. Slide a stone
3. Check web UI for times

**Expected values:**
- Tee → Hog: 2.8-3.3 seconds (typical delivery)
- Hog → Hog: 8-14 seconds (depends on stone weight)

## Troubleshooting

### "No triggers detected"

1. Check sensor wiring (especially ground!)
2. Test sensor: `sudo python /opt/rocktimer/tools/test_sensor.py`
3. Verify laser is hitting sensor (sensor LED should light up)
4. Check logs: `sudo journalctl -u rocktimer-sensor -f`

### "Can't connect to rocktimer Wi-Fi"

1. Check hostapd: `sudo systemctl status hostapd`
2. Verify IP: `ip addr show wlan0` (should be 192.168.50.1)
3. Restart services: `sudo systemctl restart dhcpcd hostapd dnsmasq`

### "Web UI not updating"

1. Hard refresh: Ctrl+Shift+R (Chrome) or Ctrl+F5 (Firefox)
2. Check WebSocket in browser console (F12)
3. Restart server: `sudo systemctl restart rocktimer-server`

### "Times are wildly wrong"

1. Check time sync: `chronyc tracking` (on all Pi's)
2. Verify Pi Zero's sync to Pi 4: `chronyc sources` (should show 192.168.50.1 with *)
3. Restart chrony: `sudo systemctl restart chrony`

## Next Steps

- **Voice announcements:** Enable in Settings (⚙️ icon in web UI)
  - Wire speaker to Pi 4 (see audio diagram in README)
- **Customize:** Edit `/opt/rocktimer/config.yaml`
- **Apple Watch:** Build companion app from `apple-watch/` directory
- **Enclosures:** 3D print cases to protect Pi units on ice

## Support

- Full documentation: See README.md
- Issues: https://github.com/jbevemyr/rocktimer/issues
- Hardware details: See "Hardware" section in README.md

## Maintenance

### Regular checks

- Battery levels (power banks + laser batteries)
- Sensor alignment (lasers can drift)
- SD card backups (especially before major tournaments)

### Software updates

```bash
cd /opt/rocktimer
sudo git pull
sudo ./install_server.sh  # or install_sensor.sh
sudo systemctl restart rocktimer-server  # or rocktimer-sensor
```

### Cleaning

- Wipe sensors/lasers (dust affects accuracy)
- Check cable connections
- Verify all screws/mounts are tight

---

**Happy timing! 🥌**

