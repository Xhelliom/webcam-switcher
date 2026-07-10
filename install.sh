#!/usr/bin/env bash
# Install webcam-switcher (script + user service + module config).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"

echo ":: script -> ~/.local/bin/webcam-switcher"
install -Dm755 "$here/webcam-switcher" "$HOME/.local/bin/webcam-switcher"

echo ":: user service -> ~/.config/systemd/user/"
install -Dm644 "$here/webcam-switcher.service" \
  "$HOME/.config/systemd/user/webcam-switcher.service"

echo ":: module config -> /etc/modprobe.d/v4l2loopback.conf (sudo)"
sudo install -Dm644 "$here/50-v4l2loopback.conf" /etc/modprobe.d/v4l2loopback.conf

# Remove a stale virtual-webcam.service that prevents exclusive_caps from sticking.
if systemctl list-unit-files virtual-webcam.service &>/dev/null; then
  echo ":: removing leftover virtual-webcam.service"
  sudo systemctl disable --now virtual-webcam.service || true
  sudo rm -f /etc/systemd/system/virtual-webcam.service
  sudo systemctl daemon-reload || true
fi

echo ":: reload v4l2loopback with exclusive_caps=1"
sudo modprobe -r v4l2loopback 2>/dev/null || true
sudo modprobe v4l2loopback

echo ":: enable the service"
systemctl --user daemon-reload
systemctl --user enable --now webcam-switcher.service

cat <<'EOF'

Done.
- Check : cat /sys/module/v4l2loopback/parameters/exclusive_caps   (expected: Y,...)
- Fully restart your browser so it re-enumerates cameras.
- The camera shows up as "Camera intégrée".
EOF
