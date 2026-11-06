import serial, glob, time, numpy as np, cv2


def connect():
    while True:
        ports = glob.glob("/dev/cu.usbserial-*") + glob.glob("/dev/cu.usbmodem*")
        if ports:
            try:
                ser = serial.Serial()
                ser.port, ser.baudrate, ser.timeout = ports[0], 460800, 5
                ser.dtr = False  # don't reset the board on open
                ser.rts = False
                ser.open()
                print("Connected to", ports[0])
                return ser
            except serial.SerialException as e:
                print("Open failed:", e)
        else:
            print("No ESP32 found, waiting...")
        time.sleep(1)


ser = connect()
while True:
    try:
        line = ser.readline().decode(errors="ignore").strip()
        if not line.startswith("F") or not line[1:].isdigit():
            if line.isprintable() and 0 < len(line) < 80:
                print("ESP32 says:", line)
            continue
        data = ser.read(int(line[1:]))
    except serial.SerialException:
        print("Board disconnected, reconnecting...")
        ser.close()
        time.sleep(1)
        ser = connect()
        continue
    frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if frame is not None:
        cv2.imshow("cam", frame)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break
