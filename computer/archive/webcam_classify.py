"""Live webcam view. Click (or SPACE) to take a picture and classify the leaf.
R = start/stop recording video, N = switch to next camera, Q = quit. Needs the classifier server running (./start.sh)."""
import os, sys, textwrap, threading, time
import cv2
import requests

SERVER = "http://localhost:8000/classify"
PHOTO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "photos")
VIDEO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "videos")
WINDOW = "Webcam - click to classify, R = record video, N = next camera, Q = quit"
os.makedirs(PHOTO_DIR, exist_ok=True)
os.makedirs(VIDEO_DIR, exist_ok=True)
writer = None

result = {"text": "Click to take a picture", "busy": False}
frame = None
flash_until = 0.0


def classify(path):
    try:
        with open(path, "rb") as f:
            r = requests.post(SERVER, files={"image": f}, timeout=120)
        d = r.json()
        result["text"] = f"{d.get('label', '?')}  ({d.get('confidence', 0) * 100:.0f}%)"
        print("\nResult:", result["text"])
        if d.get("explanation"):
            print(textwrap.fill(d["explanation"], 90))
    except requests.ConnectionError:
        result["text"] = "Server not running - start it with ./start.sh"
        print(result["text"])
    except Exception as e:
        result["text"] = f"Error: {e}"
        print(result["text"])
    result["busy"] = False


def take_picture():
    global flash_until
    if frame is None or result["busy"]:
        return
    path = os.path.join(PHOTO_DIR, time.strftime("webcam_%Y%m%d_%H%M%S.jpg"))
    cv2.imwrite(path, frame)
    print("Saved", path)
    flash_until = time.time() + 0.3
    result["busy"] = True
    result["text"] = "Classifying..."
    threading.Thread(target=classify, args=(path,), daemon=True).start()


def on_mouse(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN:
        take_picture()


def toggle_recording():
    global writer
    if writer is not None:
        writer.release()
        writer = None
        print("Recording stopped")
        return
    if frame is None:
        return
    path = os.path.join(VIDEO_DIR, time.strftime("video_%Y%m%d_%H%M%S.mp4"))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    h, w = frame.shape[:2]
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    print("Recording to", path)


def open_camera(i):
    cap = cv2.VideoCapture(i)
    if cap.isOpened():
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    return cap


cam_index = int(sys.argv[1]) if len(sys.argv) > 1 else 0
cap = open_camera(cam_index)
cv2.namedWindow(WINDOW)
cv2.setMouseCallback(WINDOW, on_mouse)

while True:
    ok, img = cap.read()
    if ok:
        frame = img
        if writer is not None:
            writer.write(img)
        view = img.copy()
        if time.time() < flash_until:
            view[:] = 255
        h = view.shape[0]
        cv2.rectangle(view, (0, h - 50), (view.shape[1], h), (0, 0, 0), -1)
        cv2.putText(view, result["text"], (12, h - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        cv2.putText(view, f"camera {cam_index}", (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        if writer is not None:
            cv2.circle(view, (view.shape[1] - 90, 25), 10, (0, 0, 255), -1)
            cv2.putText(view, "REC", (view.shape[1] - 70, 33), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        cv2.imshow(WINDOW, view)
    key = cv2.waitKey(1) & 0xFF
    if key == ord("q"):
        break
    if key == ord(" "):
        take_picture()
    if key == ord("r"):
        toggle_recording()
    if key == ord("n") or not cap.isOpened():
        if writer is not None:
            toggle_recording()
        cap.release()
        cam_index = (cam_index + 1) % 4
        print("Switching to camera", cam_index)
        cap = open_camera(cam_index)

if writer is not None:
    writer.release()
cap.release()
cv2.destroyAllWindows()
