#!/usr/bin/env python3
"""webcam-switcher — on-demand IPU6 (ov08x40) webcam via v4l2loopback.

A single, PERSISTENT producer feeds the loopback: appsrc -> videoconvert ->
v4l2sink. It never stops, so a consumer (Teams/Chrome via PipeWire) never sees
the producer disappear -> no disconnect. What feeds that appsrc is swapped:

  - idle: a black source (videotestsrc) -> the device stays LISTED, but libcamera
    is NOT running, so the sensor and its privacy LED are OFF.
  - in use: the real camera (libcamerasrc, software ISP debayered on the Intel
    iGPU via Mesa) -> LED on. The black source keeps feeding until the camera's
    first real frame arrives, then the feed hands over -> seamless, no gap.

Notes:
  - Only the camera pipeline is started/stopped (that drives the LED); the black
    source stays running but only pushes while it's the selected source.
  - Pushed buffers are re-timestamped by appsrc (their PTS is cleared); the two
    sources are on different clocks, and keeping their timestamps makes v4l2sink
    drop "late" frames at the hand-over and the consumer stalls.
  - All pipeline state changes happen on the main thread (never from a
    streaming-thread callback, which would deadlock).

See README for the Mesa-EGL / full-frame-then-scale rationale.
"""
import os
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

DEV   = os.environ.get("WEBCAM_DEV", "/dev/video0")
W     = int(os.environ.get("WEBCAM_WIDTH", "1280"))
H     = int(os.environ.get("WEBCAM_HEIGHT", "720"))
GRACE = int(os.environ.get("WEBCAM_GRACE", "3"))          # seconds before going idle
EV    = os.environ.get("WEBCAM_EV", "-2.0")                # AE target compensation, see README

# Force the software ISP onto the Intel iGPU (Mesa), not the NVIDIA dGPU.
os.environ.setdefault("__EGL_VENDOR_LIBRARY_FILENAMES",
                      "/usr/share/glvnd/egl_vendor.d/50_mesa.json")
os.environ["LIBCAMERA_SOFTISP_MODE"] = "gpu"

CAPS = f"video/x-raw,format=YUY2,width={W},height={H}"
MYPID = str(os.getpid())

Gst.init(None)

# Persistent output producer — never leaves PLAYING.
out = Gst.parse_launch(
    f"appsrc name=src is-live=true do-timestamp=true format=time "
    f"caps={CAPS},framerate=30/1 ! queue max-size-buffers=4 leaky=downstream "
    f"! videoconvert ! v4l2sink device={DEV} sync=false"
)
appsrc = out.get_by_name("src")

SRC = "black"   # which feeder may currently push into appsrc

def feeder(name, desc):
    p = Gst.parse_launch(desc + " ! appsink name=o emit-signals=true max-buffers=2 drop=true sync=false")
    def on_sample(sink):
        global SRC
        sample = sink.emit("pull-sample")
        if sample:
            if name == "camera" and SRC != "camera":
                SRC = "camera"                        # first real frame -> hand over
            if SRC == name:
                buf = sample.get_buffer().copy()
                buf.pts = buf.dts = buf.duration = Gst.CLOCK_TIME_NONE
                appsrc.emit("push-buffer", buf)
        return Gst.FlowReturn.OK
    p.get_by_name("o").connect("new-sample", on_sample)
    return p

black = feeder("black", f"videotestsrc pattern=black is-live=true ! {CAPS},framerate=15/1")
camera = feeder("camera",
    f"libcamerasrc exposure-value={EV} ! video/x-raw,width=3840,height=2160 "
    f"! videoscale ! videoconvert ! {CAPS}")

out.set_state(Gst.State.PLAYING)
black.set_state(Gst.State.PLAYING)      # always running (cheap), gated by SRC
mode = "idle"
gone = 0

def has_consumer():
    # Pure-Python /proc scan instead of shelling out to `fuser`: fuser can
    # occasionally hang for a long time on a busy system (many processes/fds
    # — e.g. a Chrome-heavy desktop), and since this runs on the GLib main
    # thread, a stuck subprocess call freezes the whole switcher — camera
    # state (and the LED) then stays frozen in whatever it was, forever.
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or pid == MYPID:
            continue
        try:
            for fd in os.listdir(f"/proc/{pid}/fd"):
                try:
                    if os.readlink(f"/proc/{pid}/fd/{fd}") == DEV:
                        return True
                except OSError:
                    pass
        except OSError:
            pass
    return False

def stop_camera():
    """Stop the camera pipeline and verify it actually reached NULL — a
    fire-and-forget set_state(NULL) can silently fail to complete (GStreamer/
    EGL teardown on this driver can hang), leaving the sensor — and its
    privacy LED — running forever even though SRC has switched back to black.
    If it doesn't confirm within 2s, kill the whole process instead: systemd
    (Restart=always) brings it back up clean in idle mode."""
    camera.set_state(Gst.State.NULL)
    _, state, _ = camera.get_state(2 * Gst.SECOND)
    if state != Gst.State.NULL:
        print(f"[webcam-switcher] camera pipeline stuck in {state} instead of NULL "
              f"— restarting to force the sensor off", flush=True)
        os._exit(1)

def tick():
    global mode, gone, SRC
    if has_consumer():
        gone = 0
        if mode == "idle":
            mode = "active"
            camera.set_state(Gst.State.PLAYING)   # LED on; black feeds until 1st cam frame
    elif mode == "active":
        gone += 1
        if gone >= GRACE:
            mode = "idle"
            SRC = "black"                          # resume splash immediately (no gap)
            stop_camera()                          # LED off, verified
    return True

GLib.timeout_add_seconds(1, tick)
loop = GLib.MainLoop()
try:
    loop.run()
except KeyboardInterrupt:
    pass
finally:
    for p in (camera, black, out):
        p.set_state(Gst.State.NULL)
