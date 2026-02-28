#!/bin/bash
# Install RockTimer Sensor on Raspberry Pi Zero 2 W

set -e

echo "==================================="
echo "RockTimer Sensor Installation"
echo "==================================="

# Ensure we run as root
if [ "$EUID" -ne 0 ]; then
    echo "Run this script as root (sudo)"
    exit 1
fi

# Install path
INSTALL_DIR="/opt/rocktimer"
USER="${SUDO_USER:-$(whoami)}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Ask for device ID (default to existing config if present)
echo ""
existing_device_id=""
if [ -f "${INSTALL_DIR}/config.yaml" ]; then
    # Accept both quoted and unquoted YAML, e.g.:
    # device_id: "tee"  OR  device_id: tee
    existing_device_id="$(sed -n -E 's/^[[:space:]]*device_id:[[:space:]]*\"?([A-Za-z0-9_]+)\"?.*/\1/p' "${INSTALL_DIR}/config.yaml" 2>/dev/null | head -n 1 || true)"
fi

if [ "${existing_device_id}" = "tee" ] || [ "${existing_device_id}" = "hog_far" ]; then
    echo "Detected existing device_id in ${INSTALL_DIR}/config.yaml: ${existing_device_id}"
    read -r -p "Keep this location? Press Enter to keep, or type tee/hog_far: " in_device
    DEVICE_ID="${in_device:-${existing_device_id}}"
else
    echo "Where is this sensor located?"
    echo "  1) tee - At the tee line"
    echo "  2) hog_far - At the far hog line"
    read -r -p "Choose (1 or 2): " CHOICE

    case $CHOICE in
        1) DEVICE_ID="tee" ;;
        2) DEVICE_ID="hog_far" ;;
        *) echo "Invalid choice"; exit 1 ;;
    esac
fi

if [ "${DEVICE_ID}" != "tee" ] && [ "${DEVICE_ID}" != "hog_far" ]; then
    echo "Invalid device_id: ${DEVICE_ID} (must be tee or hog_far)"
    exit 1
fi

echo "Configuring as: ${DEVICE_ID}"

echo "Installing for user: ${USER}"
echo "Source directory: ${SCRIPT_DIR}"

echo "[1/5] Installing system dependencies..."
apt-get update
apt-get install -y \
    python3-pip \
    python3-venv \
    python3-lgpio \
    python3-gpiozero \
    chrony \
    tar

echo "[2/5] Creating install directory..."
mkdir -p "${INSTALL_DIR}"

# Copy source into /opt/rocktimer (safe to re-run).
# If the script is already running from /opt/rocktimer, do NOT copy recursively into itself.
if [ "${SCRIPT_DIR}" != "${INSTALL_DIR}" ]; then
    echo "Copying files to ${INSTALL_DIR}..."
    tar \
        --exclude='./venv' \
        --exclude='./__pycache__' \
        --exclude='./.pytest_cache' \
        --exclude='./config.yaml' \
        -cf - -C "${SCRIPT_DIR}" . | tar -xpf - -C "${INSTALL_DIR}"
else
    echo "NOTE: Running from ${INSTALL_DIR}; skipping copy step."
fi

chown -R "${USER}:${USER}" "${INSTALL_DIR}"

echo "[3/5] Creating Python virtual environment..."
cd ${INSTALL_DIR}
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements-sensor.txt

echo "[4/5] Copying and configuring..."
if [ ! -f ${INSTALL_DIR}/config.yaml ]; then
    cp ${INSTALL_DIR}/config.yaml.example ${INSTALL_DIR}/config.yaml
fi

# Set device_id
# Replace the entire device_id line regardless of previous value.
sed -i -E "s/^[[:space:]]*device_id:[[:space:]]*.*/device_id: \"${DEVICE_ID}\"/" ${INSTALL_DIR}/config.yaml

echo "[4b/5] Optional: configuring time sync (chrony)..."
CHRONY_CONF="/etc/chrony/chrony.conf"
CHRONY_MARKER_BEGIN="# RockTimer chrony begin"
CHRONY_MARKER_END="# RockTimer chrony end"
CHRONY_SERVER_DEFAULT="192.168.50.1"
CHRONY_SERVER="${ROCKTIMER_CHRONY_SERVER:-${CHRONY_SERVER_DEFAULT}}"
CONFIGURE_CHRONY="${ROCKTIMER_CONFIGURE_CHRONY:-}"

if [ "${CONFIGURE_CHRONY}" = "1" ]; then
    configure_chrony="y"
elif [ "${CONFIGURE_CHRONY}" = "0" ]; then
    configure_chrony="n"
else
    read -r -p "Configure chrony time sync (recommended)? [Y/n] " configure_chrony
    configure_chrony="${configure_chrony:-y}"
fi

if [[ "${configure_chrony}" =~ ^[Yy]$ ]]; then
    if [ ! -f "${CHRONY_CONF}" ]; then
        echo "WARNING: ${CHRONY_CONF} not found; skipping chrony config"
    else
        CHRONY_MAKESTEP_THRESHOLD_DEFAULT="1.0"
        CHRONY_MAKESTEP_LIMIT_DEFAULT="3"
        CHRONY_MAKESTEP_THRESHOLD="${ROCKTIMER_CHRONY_MAKESTEP_THRESHOLD:-${CHRONY_MAKESTEP_THRESHOLD_DEFAULT}}"
        CHRONY_MAKESTEP_LIMIT="${ROCKTIMER_CHRONY_MAKESTEP_LIMIT:-${CHRONY_MAKESTEP_LIMIT_DEFAULT}}"

        # Allow interactive override unless env var is set
        if [ -z "${ROCKTIMER_CHRONY_SERVER:-}" ]; then
            read -r -p "Chrony server IP/hostname [${CHRONY_SERVER}]: " in_server
            CHRONY_SERVER="${in_server:-${CHRONY_SERVER}}"
        fi

        tmp="$(mktemp)"
        # Remove any previous RockTimer chrony block
        awk -v b="${CHRONY_MARKER_BEGIN}" -v e="${CHRONY_MARKER_END}" '
          $0==b {skip=1; next}
          $0==e {skip=0; next}
          !skip {print}
        ' "${CHRONY_CONF}" > "${tmp}"
        cat "${tmp}" > "${CHRONY_CONF}"
        rm -f "${tmp}"

        cat >> "${CHRONY_CONF}" << EOF

${CHRONY_MARKER_BEGIN}
# Prefer RockTimer Pi 4 as time source
server ${CHRONY_SERVER} iburst prefer
# Allow stepping the clock at boot if offset is large (helps if devices were powered off for a long time)
makestep ${CHRONY_MAKESTEP_THRESHOLD} ${CHRONY_MAKESTEP_LIMIT}
${CHRONY_MARKER_END}
EOF

        systemctl enable chrony >/dev/null 2>&1 || true
        systemctl restart chrony >/dev/null 2>&1 || systemctl start chrony >/dev/null 2>&1 || true
        echo "Chrony configured (client). Server: ${CHRONY_SERVER}"
    fi
else
    echo "Skipping chrony configuration."
fi

echo "[5/5] Installing systemd service..."

cat > /etc/systemd/system/rocktimer-sensor.service << EOF
[Unit]
Description=RockTimer Sensor Daemon
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
Environment="PATH=${INSTALL_DIR}/venv/bin"
ExecStart=${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/sensor/sensor_daemon.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable rocktimer-sensor.service

echo ""
echo "==================================="
echo "Installation complete!"
echo "==================================="
echo ""
echo "Device ID: ${DEVICE_ID}"
echo ""
echo "Start the sensor:"
echo "  sudo systemctl start rocktimer-sensor"
echo ""
echo "Check status:"
echo "  sudo systemctl status rocktimer-sensor"
echo ""
echo "View logs:"
echo "  sudo journalctl -u rocktimer-sensor -f"
echo ""
echo "Edit configuration:"
echo "  nano ${INSTALL_DIR}/config.yaml"
echo ""

