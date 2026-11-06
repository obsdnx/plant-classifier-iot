"""Send a spoken sentence to the ESP32 over USB serial.

Usage:
  python3 speak_serial.py "Hello, I am your plant health hat."
  python3 speak_serial.py --port /dev/cu.usbserial-10 "Some text here"

The script uses macOS 'say' to generate 8 kHz audio, then sends it to the
ESP32 using the magic-header protocol expected by sound_test.ino.
"""
import sys, subprocess, struct, time, wave, tempfile, os, glob

BAUD     = 115200
MAGIC    = b'\xaa\xbb'
RATE     = 8000
MAX_WAIT = 10  # seconds to wait for READY after reset


def find_port():
    candidates = glob.glob("/dev/cu.usbserial-*") + glob.glob("/dev/cu.usbmodem*")
    if not candidates:
        sys.exit("No ESP32 serial port found. Plug in the board.")
    if len(candidates) == 1:
        return candidates[0]
    print("Multiple ports found:")
    for i, p in enumerate(candidates):
        print(f"  {i}: {p}")
    idx = int(input("Choose: "))
    return candidates[idx]


def generate_audio(text: str) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name
    subprocess.run(
        ["say", "-r", "160", "-o", wav_path,
         "--file-format=WAVE", "--data-format=UI8@8000", text],
        check=True
    )
    with wave.open(wav_path) as w:
        raw = w.readframes(w.getnframes())
    os.unlink(wav_path)
    return raw[:RATE * 12]  # cap at 12 seconds


def send(port: str, audio: bytes):
    import serial  # pyserial
    ser = serial.Serial(port, BAUD, timeout=2)
    time.sleep(0.5)          # let ESP32 boot if just flashed
    ser.reset_input_buffer()

    # Step 1: send magic + length header
    header = MAGIC + struct.pack("<I", len(audio))
    print(f"Sending header ({len(audio)} bytes of audio, {len(audio)/RATE:.1f}s) to {port}...")
    ser.write(header)
    ser.flush()

    # Step 2: wait for ESP32 to ACK with "RECV <n>"
    print("Waiting for ESP32 ACK...")
    deadline = time.time() + 5
    while time.time() < deadline:
        line = ser.readline().decode(errors="ignore").strip()
        if line:
            print("ESP32:", line)
        if line.startswith("RECV"):
            break
    else:
        print("No ACK — is the new sketch uploaded? Try again.")
        ser.close(); return

    # Step 3: send audio bytes
    t0 = time.time()
    ser.write(audio)
    ser.flush()
    print(f"Audio sent in {time.time()-t0:.2f}s — waiting for DONE...")

    deadline = time.time() + 20
    while time.time() < deadline:
        line = ser.readline().decode(errors="ignore").strip()
        if line:
            print("ESP32:", line)
        if line == "DONE":
            break
    ser.close()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default=None)
    parser.add_argument("text", nargs="+")
    args = parser.parse_args()

    text = " ".join(args.text)
    port = args.port or find_port()

    print(f'Generating audio for: "{text}"')
    audio = generate_audio(text)
    print(f"Audio: {len(audio)} bytes, {len(audio)/RATE:.1f}s")
    send(port, audio)


if __name__ == "__main__":
    main()
