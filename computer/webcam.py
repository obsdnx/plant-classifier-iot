"""Server-side laptop/USB webcam capture.

Runs a background thread that keeps the latest frame from the camera,
serves it as an MJPEG stream, and provides single-frame JPEG captures
for the analysis pipeline.
"""
import threading, time
import cv2

_cap = None
_lock = threading.Lock()
_latest_jpeg: bytes | None = None
_running = False
_device = 0


def start(device: int = 0) -> bool:
    global _cap, _running, _device
    with _lock:
        if _running:
            return True
        cap = cv2.VideoCapture(device)
        if not cap.isOpened():
            return False
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        _cap = cap
        _device = device
        _running = True
    threading.Thread(target=_loop, daemon=True).start()
    return True


def stop():
    global _running, _cap
    _running = False
    if _cap:
        _cap.release()
        _cap = None


def _loop():
    global _latest_jpeg, _running
    while _running:
        with _lock:
            if _cap is None:
                break
            ok, frame = _cap.read()
        if ok:
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            _latest_jpeg = buf.tobytes()
        time.sleep(0.04)  # ~25 fps


def capture() -> bytes | None:
    return _latest_jpeg


def is_ready() -> bool:
    return _running and _latest_jpeg is not None


def mjpeg_generator():
    """Yield MJPEG boundary frames for a multipart/x-mixed-replace response."""
    while True:
        frame = _latest_jpeg
        if frame:
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"
                + frame
                + b"\r\n"
            )
        time.sleep(0.05)
