"""Live view from the OV7670 on the ESP32-S3 over USB. Click the window (or press SPACE) to save a photo.
Photos go to computer/photos/. Press Q to quit."""
import glob, os, time
import cv2
import numpy as np
import serial

PHOTO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "photos")
WINDOW = "ESP32 camera - click to take a picture, Q to quit"
os.makedirs(PHOTO_DIR, exist_ok=True)

latest = None
flash_until = 0.0


def save_photo():
    global flash_until
    if latest is None:
        print("No picture yet, wait for the first frame")
        return
    path = os.path.join(PHOTO_DIR, time.strftime("photo_%Y%m%d_%H%M%S.jpg"))
    cv2.imwrite(path, latest)
    flash_until = time.time() + 0.3
    print("Saved", path)


def on_mouse(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN:
        save_photo()


def open_port():
    ports = glob.glob("/dev/cu.usbmodem*")
    return serial.Serial(ports[0], 115200, timeout=5) if ports else None


def connect():
    while True:
        ports = glob.glob("/dev/cu.usbmodem*")
        if ports:
            try:
                ser = open_port()
                # restart the board so the picture stream starts cleanly from the first frame
                ser.dtr = False
                ser.rts = True
                time.sleep(0.1)
                ser.rts = False
                ser.close()
                time.sleep(4)
                ser = open_port()
                if ser:
                    print("Connected to", ports[0])
                    return ser
            except serial.SerialException as e:
                print("Open failed (is the Arduino Serial Monitor open?):", e)
        else:
            print("No ESP32 found, waiting...")
        time.sleep(1)


cv2.namedWindow(WINDOW)
cv2.setMouseCallback(WINDOW, on_mouse)
ser = connect()

while True:
    try:
        line = ser.readline().decode(errors="ignore").strip()
        if line.startswith("R"):
            w, h, n = map(int, line[1:].split())
            data = ser.read(n)
            if len(data) == n:
                yuyv = np.frombuffer(data, np.uint8).reshape(h, w, 2)
                latest = cv2.cvtColor(yuyv, cv2.COLOR_YUV2BGR_YUYV)
        elif line.startswith(("CAM_", "NO_FRAME")):
            print("ESP32 says:", line)
    except (serial.SerialException, ValueError):
        print("Board disconnected, reconnecting...")
        ser.close()
        time.sleep(1)
        ser = connect()
        continue

    if latest is not None:
        view = cv2.resize(latest, (640, 480))
        if time.time() < flash_until:
            view = cv2.addWeighted(view, 0.3, np.full_like(view, 255), 0.7, 0)
        cv2.imshow(WINDOW, view)

    key = cv2.waitKey(1) & 0xFF
    if key == ord(" "):
        save_photo()
    elif key == ord("q"):
        break

ser.close()
cv2.destroyAllWindows()
