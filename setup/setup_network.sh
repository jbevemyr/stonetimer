#!/bin/bash
# Network configuration for StoneTimer
# Run on Pi 4 to set up a WiFi Access Point

set -e

echo "==================================="
echo "StoneTimer Network Configuration"
echo "==================================="

# Ensure root
if [ "$EUID" -ne 0 ]; then
    echo "Run as root (sudo)"
    exit 1
fi

# Variables
SSID="${STONETIMER_SSID:-stonetimer}"
PASSWORD="${STONETIMER_PASSWORD:-stonetimer}"
IP_ADDRESS="${STONETIMER_IP_ADDRESS:-192.168.50.1}"
SUBNET_CIDR="${STONETIMER_SUBNET_CIDR:-192.168.50.0/24}"
AP_INTERFACE="${STONETIMER_AP_INTERFACE:-wlan0}"
# Wi-Fi regulatory domain / country code for hostapd (improves client compatibility)
COUNTRY_CODE="${STONETIMER_COUNTRY_CODE:-SE}"
# Internet sharing (NAT) is enabled by default so Pi Zero clients can reach the internet
# via the Pi 4 uplink (typically eth0). Set STONETIMER_ENABLE_INTERNET_SHARING=0 to disable.
ENABLE_INTERNET_SHARING="${STONETIMER_ENABLE_INTERNET_SHARING:-1}"
# Uplink interface used for internet access when sharing is enabled (typically eth0 if Pi 4 is wired)
UPLINK_INTERFACE="${STONETIMER_UPLINK_INTERFACE:-eth0}"
CH_DHCPCD_BEGIN="# StoneTimer AP begin"
CH_DHCPCD_END="# StoneTimer AP end"

echo "[1/4] Installing hostapd and dnsmasq..."
apt-get update
apt-get install -y hostapd dnsmasq

echo "[2/4] Stopping services..."
systemctl stop hostapd || true
systemctl stop dnsmasq || true

echo "[3/4] Configuring interface IP (${AP_INTERFACE} -> ${IP_ADDRESS}/24)..."

# Prefer dhcpcd when it exists and is used by the OS (classic Raspberry Pi OS setup).
# On newer Debian/Raspberry Pi OS variants NetworkManager is often used and dhcpcd.service may be absent.
if systemctl list-unit-files 2>/dev/null | grep -qE '^dhcpcd\.service'; then
    echo "Using dhcpcd for static IP."
    tmp="$(mktemp)"
    awk -v b="${CH_DHCPCD_BEGIN}" -v e="${CH_DHCPCD_END}" '
      $0==b {skip=1; next}
      $0==e {skip=0; next}
      !skip {print}
    ' /etc/dhcpcd.conf > "${tmp}"
    cat "${tmp}" > /etc/dhcpcd.conf
    rm -f "${tmp}"

    cat >> /etc/dhcpcd.conf << EOF

${CH_DHCPCD_BEGIN}
# StoneTimer Access Point
interface ${AP_INTERFACE}
    static ip_address=${IP_ADDRESS}/24
    nohook wpa_supplicant
${CH_DHCPCD_END}
EOF

    systemctl enable dhcpcd >/dev/null 2>&1 || true
else
    echo "dhcpcd.service not found; configuring NetworkManager/systemd-networkd (common on newer OS images)."

    # Ensure NetworkManager does not manage the AP interface (hostapd needs full control).
    if systemctl is-active --quiet NetworkManager 2>/dev/null; then
        mkdir -p /etc/NetworkManager/conf.d
        cat > /etc/NetworkManager/conf.d/99-stonetimer-unmanaged-wlan0.conf << EOF
[keyfile]
unmanaged-devices=interface-name:${AP_INTERFACE}
EOF
        systemctl restart NetworkManager || true
    fi

    # Configure static IP via systemd-networkd for just the AP interface.
    mkdir -p /etc/systemd/network
    cat > /etc/systemd/network/99-stonetimer-${AP_INTERFACE}.network << EOF
[Match]
Name=${AP_INTERFACE}

[Network]
Address=${IP_ADDRESS}/24
ConfigureWithoutCarrier=yes
EOF
    systemctl enable systemd-networkd >/dev/null 2>&1 || true
    systemctl restart systemd-networkd || true
fi

echo "[4/4] Configuring hostapd..."
cat > /etc/hostapd/hostapd.conf << EOF
interface=${AP_INTERFACE}
driver=nl80211
country_code=${COUNTRY_CODE}
ieee80211d=1
ssid=${SSID}
hw_mode=g
channel=7
wmm_enabled=1
ieee80211n=1
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=${PASSWORD}
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
EOF

# Enable hostapd
sed -i 's/#DAEMON_CONF=""/DAEMON_CONF="\/etc\/hostapd\/hostapd.conf"/' /etc/default/hostapd

echo "Configuring dnsmasq (DHCP + DNS)..."
cp -n /etc/dnsmasq.conf /etc/dnsmasq.conf.orig || true
cat > /etc/dnsmasq.conf << EOF
interface=${AP_INTERFACE}
domain-needed
bogus-priv
expand-hosts

# DHCP range for StoneTimer network
dhcp-range=192.168.50.10,192.168.50.100,255.255.255.0,24h

# Advertise Pi 4 as the default gateway for clients
dhcp-option=option:router,${IP_ADDRESS}

# Make the hostname 'stonetimer' resolve to the Pi 4 (this server)
address=/stonetimer/${IP_ADDRESS}

# Optional: also support stonetimer.local
address=/stonetimer.local/${IP_ADDRESS}

# Help phones accept this Wi-Fi even without internet by answering common
# captive-portal / connectivity check domains locally.
# (They will resolve to the Pi 4, and nginx on port 80 can respond.)
address=/connectivitycheck.gstatic.com/${IP_ADDRESS}
address=/clients3.google.com/${IP_ADDRESS}
address=/connectivitycheck.android.com/${IP_ADDRESS}
address=/captive.apple.com/${IP_ADDRESS}
address=/library.captive.apple.com/${IP_ADDRESS}
address=/www.apple.com/${IP_ADDRESS}
address=/www.msftconnecttest.com/${IP_ADDRESS}
address=/msftconnecttest.com/${IP_ADDRESS}
address=/www.msftncsi.com/${IP_ADDRESS}
address=/msftncsi.com/${IP_ADDRESS}

# Provide a search domain so some clients can type http://stonetimer
dhcp-option=option:domain-name,stonetimer
dhcp-option=option:domain-search,stonetimer
EOF

echo "Enabling services..."
systemctl unmask hostapd
systemctl enable hostapd
systemctl enable dnsmasq

# Try to bring the interface up immediately (some OS images keep it down until hostapd starts).
ip link set "${AP_INTERFACE}" up 2>/dev/null || true

# Start services now so the AP comes up immediately (no reboot needed for first test).
systemctl daemon-reload >/dev/null 2>&1 || true
systemctl restart hostapd dnsmasq || true

uplink_ok=1
if [ "${ENABLE_INTERNET_SHARING}" = "1" ]; then
  # Best-effort guard: don't try NAT if uplink interface doesn't exist.
  if ! ip link show "${UPLINK_INTERFACE}" >/dev/null 2>&1; then
    uplink_ok=0
    echo "WARNING: Uplink interface '${UPLINK_INTERFACE}' not found; skipping internet sharing."
  fi
  # Also require a default route via the uplink (otherwise clients won't reach the internet anyway).
  if [ "${uplink_ok}" = "1" ] && ! ip route show default 2>/dev/null | grep -q " dev ${UPLINK_INTERFACE}"; then
    uplink_ok=0
    echo "WARNING: No default route via '${UPLINK_INTERFACE}'; skipping internet sharing."
  fi
fi

if [ "${ENABLE_INTERNET_SHARING}" = "1" ] && [ "${uplink_ok}" = "1" ]; then
  echo ""
  echo "Enabling internet sharing (NAT) from ${SUBNET_CIDR} via ${UPLINK_INTERFACE}..."

  # Enable IPv4 forwarding (runtime + persistent)
  echo 1 > /proc/sys/net/ipv4/ip_forward || true
  mkdir -p /etc/sysctl.d
  cat > /etc/sysctl.d/99-stonetimer-ipforward.conf << EOF
net.ipv4.ip_forward=1
EOF
  systemctl restart systemd-sysctl >/dev/null 2>&1 || true

  # Use nftables for NAT/firewall (preferred on modern Debian/RPi OS).
  apt-get install -y nftables
  systemctl enable nftables >/dev/null 2>&1 || true

  mkdir -p /etc/nftables.d
  cat > /etc/nftables.d/stonetimer.nft << EOF
# StoneTimer NAT + forwarding (generated by setup_network.sh)
table inet stonetimer_filter {
  chain forward {
    type filter hook forward priority 0; policy drop;
    ct state established,related accept
    iifname "${AP_INTERFACE}" oifname "${UPLINK_INTERFACE}" accept
  }
}

table ip stonetimer_nat {
  chain postrouting {
    type nat hook postrouting priority 100;
    oifname "${UPLINK_INTERFACE}" ip saddr ${SUBNET_CIDR} masquerade
  }
}
EOF

  # Ensure /etc/nftables.conf includes /etc/nftables.d/*.nft
  if [ ! -f /etc/nftables.conf ]; then
    cat > /etc/nftables.conf <<'EOF'
#!/usr/sbin/nft -f

include "/etc/nftables.d/*.nft"
EOF
  elif ! grep -q '/etc/nftables.d' /etc/nftables.conf; then
    cp -n /etc/nftables.conf /etc/nftables.conf.stonetimer.bak || true
    printf '\ninclude "/etc/nftables.d/*.nft"\n' >> /etc/nftables.conf
  fi

  systemctl restart nftables || true
  echo "Internet sharing enabled."
fi

echo ""
echo "==================================="
echo "Configuration complete!"
echo "==================================="
echo ""
echo "WiFi SSID: ${SSID}"
echo "Password: ${PASSWORD}"
echo "Server IP: ${IP_ADDRESS}"
if [ "${ENABLE_INTERNET_SHARING}" = "1" ]; then
  if [ "${uplink_ok}" = "1" ]; then
    echo "Internet sharing: ENABLED (uplink: ${UPLINK_INTERFACE})"
  else
    echo "Internet sharing: skipped (no uplink via ${UPLINK_INTERFACE})"
  fi
else
  echo "Internet sharing: disabled (set STONETIMER_ENABLE_INTERNET_SHARING=1 to enable)"
fi
echo ""
echo "Reboot to apply:"
echo "  sudo reboot"
echo ""

