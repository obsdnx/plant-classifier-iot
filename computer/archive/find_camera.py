"""Tests camera numbers 0-4 and reports which ones give a real picture."""
import time
import cv2

for i in range(5):
    cap = cv2.VideoCapture(i)
    if not cap.isOpened():
        print(f"camera {i}: not found")
        continue
    brightness = 0.0
    for _ in range(30):  # cameras often send black frames while starting up
        ok, f = cap.read()
        if ok and f is not None:
            brightness = f.mean()
            if brightness > 5:
                break
        time.sleep(0.1)
    cap.release()
    print(f"camera {i}: {'PICTURE' if brightness > 5 else 'black'} (brightness {brightness:.0f})")
