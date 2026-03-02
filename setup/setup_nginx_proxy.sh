#!/bin/bash
# Optional: configure Nginx to serve StoneTimer on port 80 and proxy to :8080
#
# This makes it possible to use:
#   http://stonetimer
# instead of:
#   http://stonetimer:8080

set -e

if [ "$EUID" -ne 0 ]; then
  echo "Run as root (sudo)"
  exit 1
fi

echo "==================================="
echo "StoneTimer Nginx Proxy Setup"
echo "==================================="

echo "[1/3] Installing nginx..."
apt-get update
apt-get install -y nginx

echo "[2/3] Writing site config..."
cat > /etc/nginx/sites-available/stonetimer << 'EOF'
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 80;
    # Catch all Host headers. This matters because phones may request
    # connectivity-check domains (Apple/Google/Microsoft) that we map to this IP.
    server_name _;

    # Captive portal / connectivity check endpoints:
    # - Android/Google: generate_204 should return HTTP 204
    location = /generate_204 { return 204; }
    location = /gen_204 { return 204; }

    # - iOS: hotspot-detect expects exact HTML with "Success"
    location = /hotspot-detect.html {
        default_type text/html;
        return 200 '<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>';
    }

    # - iOS 14+: library.captive.apple.com
    location = /success.html {
        default_type text/html;
        return 200 '<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>';
    }

    # - Microsoft: expected small text files
    location = /connecttest.txt {
        default_type text/plain;
        return 200 "Microsoft Connect Test";
    }
    location = /ncsi.txt {
        default_type text/plain;
        return 200 "Microsoft NCSI";
    }

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_read_timeout 3600;
        proxy_send_timeout 3600;
    }
}
EOF

rm -f /etc/nginx/sites-enabled/default || true
ln -sf /etc/nginx/sites-available/stonetimer /etc/nginx/sites-enabled/stonetimer

echo "[3/3] Restarting nginx..."
nginx -t
systemctl enable nginx
systemctl restart nginx

echo ""
echo "Done."
echo "You can now use:"
echo "  http://stonetimer"
echo "  http://stonetimer.local"
echo "  http://192.168.50.1"


