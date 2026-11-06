"""
Reads photos from ESP32-CAM over USB serial and sends them to the classifier.

Usage:
  python serial_client.py                  # auto-detect port
  python serial_client.py --port /dev/tty.usbserial-XXXX
  python serial_client.py --trigger        # send CAPTURE command instead of waiting for button

Requirements:
  pip install pyserial requests
"""

import argparse
import time
import sys
import glob
import requests
import serial

SERVER_URL = "http://localhost:8000/classify"
BAUD_RATE  = 460800


def find_port():
    candidates = (
        glob.glob("/dev/tty.usbserial-*") +
        glob.glob("/dev/ttyUSB*") +
        glob.glob("/dev/ttyACM*") +
        glob.glob("COM[0-9]*")
    )
    if not candidates:
        print("ERROR: No serial port found. Connect the ESP32 and try again.")
        print("       Or specify with:  python serial_client.py --port /dev/tty.usbserial-XXXX")
        sys.exit(1)
    if len(candidates) > 1:
        print("Multiple ports found:")
        for i, p in enumerate(candidates):
            print(f"  {i}: {p}")
        idx = int(input("Which one? "))
        return candidates[idx]
    return candidates[0]


def classify(image_bytes: bytes) -> dict:
    resp = requests.post(
        SERVER_URL,
        files={"image": ("leaf.jpg", image_bytes, "image/jpeg")},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def show_result(result: dict):
    status      = result.get("status", "error")
    label       = result.get("label", "unknown")
    confidence  = result.get("confidence", 0)
    explanation = result.get("explanation", "")

    print("\n" + "=" * 50)
    if status == "ok":
        print(f"RESULT:     {label}")
        print(f"CONFIDENCE: {confidence*100:.0f}%")
        print(f"\n{explanation}")
    elif status == "unsure":
        print(f"UNSURE ({confidence*100:.0f}%): {explanation}")
    else:
        print(f"ERROR: {explanation}")
    print("=" * 50 + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port",    help="Serial port (e.g. /dev/tty.usbserial-XXXX)")
    parser.add_argument("--trigger", action="store_true",
                        help="Send CAPTURE command to ESP32 instead of waiting for button")
    args = parser.parse_args()

    port = args.port or find_port()
    print(f"Connecting to {port} at {BAUD_RATE} baud...")

    ser = serial.Serial(port, BAUD_RATE, timeout=10)
    time.sleep(2)   # let ESP32 boot

    # Wait for READY
    while True:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if line == "READY":
            print("ESP32 ready.")
            break
        if line:
            print(f"[ESP32] {line}")

    if args.trigger:
        print("Sending CAPTURE command...")
        ser.write(b"CAPTURE\n")
    else:
        print("Press the flash button on the ESP32-CAM to capture.")

    print("Waiting for photo...\n")

    while True:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if not line:
            continue

        if line.startswith("IMG:"):
            length = int(line.split(":")[1])
            print(f"Receiving {length} bytes...")
            image_bytes = ser.read(length)
            print(f"Received {len(image_bytes)} bytes. Classifying...")

            try:
                result = classify(image_bytes)
                show_result(result)
            except requests.exceptions.ConnectionError:
                print("ERROR: Cannot reach server at localhost:8000. Is ./start.sh running?")
            except Exception as e:
                print(f"ERROR: {e}")

            if args.trigger:
                break   # one shot
            print("Press button again for another capture.\n")

        elif line.startswith("ERROR:"):
            print(f"ESP32 error: {line}")
        elif line:
            print(f"[ESP32] {line}")


if __name__ == "__main__":
    main()
