# webcam-switcher

**On-demand internal webcam for Intel IPU6 (MIPI) laptops** using the **mainline
libcamera software ISP**, with automatic **privacy-LED** handling — for **hybrid
Intel + NVIDIA** machines where the proprietary Intel camera stack is dead and
`v4l2-relayd` won't cooperate.

If your IPU6 laptop webcam shows up **black**, at **2–3 fps**, or **not at all**
in Chrome / Microsoft Teams / Zoom / Google Meet on Linux, this is for you.

## Tested / compatible hardware

- **Laptop:** Dell Pro Max 14 Premium (also relevant to Dell Pro Max 16, XPS,
  Latitude, Lenovo ThinkPad, HP EliteBook — any IPU6 MIPI webcam laptop).
- **CPU / IPU:** Intel **Core Ultra 7 265H** (**Arrow Lake-H**, IPU6 `8086:7d19`).
  Should also apply to **Meteor Lake** (Core Ultra 1xx) and **Lunar Lake** class
  IPU6 parts.
- **Sensor:** OmniVision **ov08x40** (`OVTI08F4`). The framerate trick applies to
  any sensor whose binned mode is throttled; the GPU-selection fix applies to any
  hybrid-GPU IPU6 laptop.
- **dGPU:** NVIDIA (e.g. **RTX PRO 2000 Blackwell**, RTX 40xx…) — the reason the
  GPU debayer must be pinned to the Intel iGPU.
- **OS:** EndeavourOS / Arch Linux, kernel 7.1, libcamera 0.7.1, Mesa 26, on
  Wayland (niri). Any distro with kernel ≥ 6.10 and libcamera ≥ 0.7 should work.

## What it does

- **Idle:** a black splash feeds the `v4l2loopback` device so it stays *listed*
  in your camera picker — but libcamera is **not** running, so the sensor and its
  **privacy LED stay off**.
- **In use:** the moment an app (Teams, Meet, OBS, Zoom…) opens the loopback, it
  switches to the real camera and streams ~21 fps 720p. LED on only while used.
- **Released:** back to the splash, LED off.

## Why it's needed (the three gotchas)

1. **The proprietary stack is dead.** Intel's `ipu6-camera-hal` / `icamerasrc`
   needs the out-of-tree PSYS driver, which stopped building around kernel 6.16.
   On a modern kernel it's a dead end (`/dev/ipu-psys0` never appears). The
   mainline path is libcamera's software ISP.
2. **Hybrid GPU picks the wrong card.** libcamera's GPU debayer uses the default
   EGL device — the **NVIDIA** dGPU here — whose driver fails the framebuffer
   (`glFrameBufferTexture2D error 36054` → `debayerGPU failed`, i.e.
   `GL_FRAMEBUFFER_INCOMPLETE_ATTACHMENT`). Forcing the **Mesa/Intel** EGL vendor
   (`__EGL_VENDOR_LIBRARY_FILENAMES=…/50_mesa.json`) fixes it and the debayer runs
   at ~57 fps on the iGPU.
3. **Binned sensor mode is slow.** `ov08x40` runs the 720p/1080p *binned* mode at
   only ~3.6 fps but the full 3856×2176 mode at ~28 fps. So we capture full-frame
   and `videoscale` down to 720p (~21 fps after scaling).

`v4l2-relayd` would normally provide the on-demand behaviour, but it crashes at
pipeline construction on this setup (`gst_element_set_state: assertion
'GST_IS_ELEMENT (element)' failed`) — hence this small Python replacement.

It keeps a **single persistent producer** (`appsrc → videoconvert → v4l2sink`)
that never stops, and swaps what feeds it (black source ↔ camera). That's the key
to not dropping the consumer: naively killing one pipeline and starting another
makes the loopback lose its producer for a moment, and Chrome/PipeWire then drops
the camera. Pushed buffers are re-timestamped, otherwise the two sources' clocks
disagree and v4l2sink stalls at the hand-over.

Two more reliability fixes worth calling out:
- Consumer detection is a pure-Python `/proc` scan, not a shell-out to `fuser`.
  `fuser` can hang for a long time on a busy desktop, and since detection runs on
  the GLib main thread, a stuck call freezes the *entire* switcher — the camera
  (and its LED) then stays stuck in whatever state it was in, forever.
- Stopping the camera pipeline verifies it actually reached `Gst.State.NULL`
  (`get_state()` with a timeout). A fire-and-forget `set_state(NULL)` can
  silently fail to complete — same symptom: LED stuck on. If it doesn't confirm,
  the whole process exits and systemd (`Restart=always`) brings it back up clean.

## Requirements

- `python` + `python-gobject` (PyGObject) and `gst-python`
- `gstreamer` + `gst-plugins-good` (`v4l2sink`), `gst-plugin-libcamera`
  (`libcamerasrc`), `gst-plugins-base` (`videoscale`/`videoconvert`/`appsrc`)
- `v4l2loopback-dkms`
- `libcamera` ≥ 0.7 (GPU software ISP) and a working **Mesa** EGL for your iGPU
- A mainline kernel with the in-tree IPU6 ISYS driver (≥ 6.10) and your sensor

## Install

```sh
./install.sh
```

This:
- installs `webcam-switcher` to `~/.local/bin/`,
- installs + enables the user service `webcam-switcher.service`,
- installs `/etc/modprobe.d/v4l2loopback.conf` (needs sudo),
- installs a `v4l2loopback-exclusive.service` that forces `exclusive_caps=1` at
  boot (see below), and removes a leftover `virtual-webcam.service` if present.

Then **fully restart your browser** so it re-enumerates cameras. The camera shows
up as **“Camera intégrée”** (rename via `card_label` in the modprobe config).

### The `exclusive_caps` catch

`exclusive_caps=1` is **required** — without it the loopback also advertises
`VIDEO_OUTPUT` and Chrome/PipeWire silently skip it (camera never listed). But
`systemd-modules-load` ignores the option from `/etc/modprobe.d` (a kmod parsing
quirk with the quoted `card_label`), so it comes back `N` on every boot. The
included `v4l2loopback-exclusive.service` works around it by reloading the module
with the explicit option early at boot. Verify with
`cat /sys/module/v4l2loopback/parameters/exclusive_caps` → `Y,…`.

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
- Consumer detection scans `/proc` (no shell-out) once a second. A very heavy
  process count could make that scan noticeably slower, though it's typically
  under 50 ms.

## Keywords

Intel IPU6 webcam Linux, MIPI camera, ov08x40, OVTI08F4, INT3472, Arrow Lake,
Meteor Lake, Core Ultra 265H, Dell Pro Max, libcamera softISP, GPU debayer,
`debayerGPU failed`, `GL_FRAMEBUFFER_INCOMPLETE_ATTACHMENT`, hybrid NVIDIA Optimus
EGL, v4l2loopback, v4l2-relayd, camera not detected, black camera, 2 fps webcam,
Microsoft Teams / Zoom / Chrome camera on Linux, privacy LED.

## License

MIT
