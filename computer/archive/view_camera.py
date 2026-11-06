"""
Displays live camera feed from ESP32-S3-CAM over USB serial.
No WiFi needed.

Usage:
  python view_camera.py
  python view_camera.py --port /dev/cu.usbserial-10

Press Q in the image window to quit.
"""

import argparse, glob, sys, time
import numpy as np
import cv2
import serial

BAUD = 921600


def find_port():
    candidates = (
        glob.glob("/dev/cu.usbserial-*") +
        glob.glob("/dev/ttyUSB*") +
        glob.glob("/dev/ttyACM*")
    )
    if not candidates:
        print("No serial port found. Plug in the ESP32 or use --port")
        sys.exit(1)
    if len(candidates) > 1:
        for i, p in enumerate(candidates):
            print(f"  {i}: {p}")
        candidates = [candidates[int(input("Which port? "))]]
    return candidates[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port")
    args = parser.parse_args()

    port = args.port or find_port()
    print(f"Opening {port} at {BAUD} baud...")
    ser = serial.Serial(port, BAUD, timeout=5)
    time.sleep(2)

    # Wait for camera ready
    while True:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if line == "CAM_READY":
            print("Camera ready. Press Q in the window to quit.")
            break
        if line == "CAM_ERROR":
            print("Camera init failed — check pin definitions in the sketch.")
            sys.exit(1)

    cv2.namedWindow("ESP32 Camera", cv2.WINDOW_NORMAL)

    while True:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if not line.startswith("FRAME:"):
            continue

        length = int(line.split(":")[1])
        data = ser.read(length)
        if len(data) != length:
            continue

        buf = np.frombuffer(data, dtype=np.uint8)
        frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if frame is None:
            continue

        cv2.imshow("ESP32 Camera", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    ser.close()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
