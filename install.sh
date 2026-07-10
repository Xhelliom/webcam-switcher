#!/usr/bin/env bash
# Installe webcam-switcher (script + service user + config module).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"

echo ":: script → ~/.local/bin/webcam-switcher"
install -Dm755 "$here/webcam-switcher" "$HOME/.local/bin/webcam-switcher"

echo ":: service user → ~/.config/systemd/user/"
install -Dm644 "$here/webcam-switcher.service" \
  "$HOME/.config/systemd/user/webcam-switcher.service"

echo ":: config module → /etc/modprobe.d/v4l2loopback.conf (sudo)"
sudo install -Dm644 "$here/50-v4l2loopback.conf" /etc/modprobe.d/v4l2loopback.conf

# Vire un ancien virtual-webcam.service qui empêche exclusive_caps de tenir.
if systemctl list-unit-files virtual-webcam.service &>/dev/null; then
  echo ":: retrait de virtual-webcam.service (leftover)"
  sudo systemctl disable --now virtual-webcam.service || true
  sudo rm -f /etc/systemd/system/virtual-webcam.service
  sudo systemctl daemon-reload || true
fi

echo ":: recharge v4l2loopback avec exclusive_caps=1"
sudo modprobe -r v4l2loopback 2>/dev/null || true
sudo modprobe v4l2loopback

echo ":: active le service"
systemctl --user daemon-reload
systemctl --user enable --now webcam-switcher.service

cat <<'EOF'

Terminé.
- Vérifie : cat /sys/module/v4l2loopback/parameters/exclusive_caps   (attendu : Y,...)
- Redémarre complètement ton navigateur pour qu'il ré-énumère les caméras.
- La caméra apparaît comme « Camera intégrée ».
EOF
