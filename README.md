# webcam-switcher

On-demand internal webcam for **Intel IPU6 (MIPI) laptops** using the **mainline
libcamera softISP**, with automatic privacy-LED handling — on hybrid
**Intel + NVIDIA** machines where the proprietary Intel camera stack is dead and
`v4l2-relayd` won't cooperate.

Tested on a **Dell Pro Max 14 (Core Ultra 7 265H, Arrow Lake-H)** with the
`ov08x40` sensor, Linux 7.1, libcamera 0.7.1, on EndeavourOS/Arch.

## What it does

- **Idle:** a black splash feeds the `v4l2loopback` device so it stays *listed*
  in your camera picker — but libcamera is **not** running, so the sensor and its
  **privacy LED stay off**.
- **In use:** the moment an app (Teams, Meet, OBS, Zoom…) opens the loopback, it
  switches to the real camera and streams ~21 fps 720p. LED on only while used.
- **Released:** back to the splash, LED off.

## Why it's needed (the three gotchas)

1. **Proprietary stack is dead.** Intel's `ipu6-camera-hal` / `icamerasrc` needs
   the out-of-tree PSYS driver, which stopped building around kernel 6.16. On a
   modern kernel it's a dead end (`/dev/ipu-psys0` never appears). The mainline
   path is libcamera's software ISP.
2. **Hybrid GPU picks the wrong card.** libcamera's GPU debayer uses the default
   EGL device — the **NVIDIA** dGPU here — whose driver fails the framebuffer
   (`glFrameBufferTexture2D error 36054` → `debayerGPU failed`). Forcing the
   **Mesa/Intel** EGL vendor (`__EGL_VENDOR_LIBRARY_FILENAMES=.../50_mesa.json`)
   fixes it and the debayer runs at ~57 fps on the iGPU.
3. **Binned sensor mode is slow.** `ov08x40` runs the 720p/1080p *binned* mode at
   only ~3.6 fps but the full 3856×2176 mode at ~28 fps. So we capture full-frame
   and `videoscale` down to 720p (~21 fps after scaling).

`v4l2-relayd` would normally provide the on-demand behaviour, but it crashes at
pipeline construction on this setup — hence this ~40-line replacement.

## Requirements

- `gstreamer` + `gst-plugins-good` (`v4l2sink`), `gst-plugin-libcamera`
  (`libcamerasrc`), `gst-plugins-base` (`videoscale`/`videoconvert`)
- `v4l2loopback-dkms`
- `libcamera` ≥ 0.7 (GPU softISP) and a working **Mesa** EGL for your iGPU
- `psmisc` (`fuser`)
- A mainline kernel with the in-tree IPU6 ISYS driver (≥ 6.10) and your sensor

## Install

```sh
./install.sh
```

This:
- installs `webcam-switcher` to `~/.local/bin/`,
- installs+enables the user service `webcam-switcher.service`,
- installs `/etc/modprobe.d/v4l2loopback.conf` (needs sudo),
- removes a leftover `virtual-webcam.service` if present.

Then reboot (or `sudo modprobe -r v4l2loopback && sudo modprobe v4l2loopback`),
and **fully restart your browser** so it re-enumerates cameras.

## Tuning

Environment variables (set them in the `.service` via `Environment=`):

- `WEBCAM_DEV` (default `/dev/video0`)
- `WEBCAM_WIDTH` / `WEBCAM_HEIGHT` (default `1280`/`720`)
- `WEBCAM_GRACE` seconds before dropping back to the splash (default `3`)

## Known limitations

- **No proper auto-exposure:** libcamera has no sensor helper for `ov08x40`, so
  brightness tracks ambient light with a crude AE (great in a lit room, dark in
  the dark). Nothing this script can fix.
- **~2–3 s freeze** when a call first turns the camera on (splash→camera + sensor
  warm-up).
- Depends on `exclusive_caps=1` actually applying at boot; verify with
  `cat /sys/module/v4l2loopback/parameters/exclusive_caps`.

## License

MIT
