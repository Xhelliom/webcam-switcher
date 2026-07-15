#!/usr/bin/env bash
# Install webcam-switcher (script + user service + module config).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"

echo ":: script -> ~/.local/bin/webcam-switcher"
install -Dm755 "$here/webcam-switcher.py" "$HOME/.local/bin/webcam-switcher"

echo ":: user service -> ~/.config/systemd/user/"
install -Dm644 "$here/webcam-switcher.service" \
  "$HOME/.config/systemd/user/webcam-switcher.service"

echo ":: module config -> /etc/modprobe.d/v4l2loopback.conf (sudo)"
sudo install -Dm644 "$here/50-v4l2loopback.conf" /etc/modprobe.d/v4l2loopback.conf

# Remove a stale virtual-webcam.service that creates a second loopback.
if systemctl list-unit-files virtual-webcam.service &>/dev/null; then
  echo ":: removing leftover virtual-webcam.service"
  sudo systemctl disable --now virtual-webcam.service || true
  sudo rm -f /etc/systemd/system/virtual-webcam.service
fi

# systemd-modules-load ignores the exclusive_caps option from modprobe.d, so a
# tiny system service reloads the module with it explicitly at boot.
echo ":: system service -> exclusive_caps=1 at boot (sudo)"
sudo install -Dm644 "$here/v4l2loopback-exclusive.service" \
  /etc/systemd/system/v4l2loopback-exclusive.service
sudo systemctl daemon-reload

# Free the loopback so the reload below succeeds.
systemctl --user stop webcam-switcher.service 2>/dev/null || true
sudo systemctl enable --now v4l2loopback-exclusive.service

echo ":: enable the switcher"
systemctl --user daemon-reload
systemctl --user enable --now webcam-switcher.service

cat <<'EOF'

Done.
- Check : cat /sys/module/v4l2loopback/parameters/exclusive_caps   (expected: Y,...)
- Fully restart your browser so it re-enumerates cameras.
- The camera shows up as "Camera intégrée".
EOF
