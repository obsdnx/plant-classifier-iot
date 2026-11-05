// Serial speaker — receives 8 kHz u8 audio from the laptop over USB and plays it via DAC.
// Speaker wired: + wire -> GPIO 26, - wire -> GND.
//
// Protocol (matches speak_serial.py):
//   laptop sends:  0xAA 0xBB <length: 4 bytes LE>
//   ESP32 replies: "RECV <length>\n"
//   laptop sends:  <audio bytes>
//   ESP32 replies: "DONE\n"
//
// Also plays a 3-beep startup tone so you know it's ready.
// Board: any ESP32 with DAC (AI Thinker, NodeMCU-32S, etc.)

#define SPEAKER  26   // DAC2 — speaker + here, - to GND
#define BAUD     115200
#define RATE     8000
#define MAGIC0   0xAA
#define MAGIC1   0xBB
#define MAX_BYTES (RATE * 12)  // 12 seconds max

// ---- DAC playback ----
void dacTone(int hz, int ms) {
  long halfUs = 500000L / hz;
  unsigned long end = millis() + ms;
  while ((long)(millis() - end) < 0) {
    dacWrite(SPEAKER, 255); delayMicroseconds(halfUs);
    dacWrite(SPEAKER, 0);   delayMicroseconds(halfUs);
  }
  dacWrite(SPEAKER, 128);  // mid-rail rest
}

void dacPlay(const uint8_t* data, uint32_t len) {
  // 8 kHz = 125 µs per sample
  for (uint32_t i = 0; i < len; i++) {
    dacWrite(SPEAKER, data[i]);
    delayMicroseconds(125);
  }
  dacWrite(SPEAKER, 128);
}

// ---- setup ----
void setup() {
  Serial.begin(BAUD);
  dacWrite(SPEAKER, 128);  // mid-rail so speaker doesn't click

  // 3-beep startup = ready
  dacTone(440, 120); delay(60);
  dacTone(660, 120); delay(60);
  dacTone(880, 180);

  Serial.println("READY");
}

// ---- main loop ----
void loop() {
  // Wait for magic header 0xAA 0xBB
  int b0 = Serial.read();
  if (b0 != MAGIC0) return;
  // give a moment for the second byte
  unsigned long t = millis();
  while (!Serial.available() && millis() - t < 200) {}
  int b1 = Serial.read();
  if (b1 != MAGIC1) return;

  // Read 4-byte little-endian length
  uint8_t lenBytes[4];
  int got = 0;
  t = millis();
  while (got < 4 && millis() - t < 1000) {
    if (Serial.available()) lenBytes[got++] = Serial.read();
  }
  if (got < 4) return;

  uint32_t len = (uint32_t)lenBytes[0]
               | ((uint32_t)lenBytes[1] << 8)
               | ((uint32_t)lenBytes[2] << 16)
               | ((uint32_t)lenBytes[3] << 24);

  if (len == 0 || len > MAX_BYTES) {
    Serial.println("ERR bad length");
    return;
  }

  // Allocate buffer and ACK
  uint8_t* buf = (uint8_t*)malloc(len);
  if (!buf) {
    Serial.println("ERR out of memory");
    return;
  }
  Serial.print("RECV ");
  Serial.println(len);

  // Receive audio bytes
  uint32_t received = 0;
  t = millis();
  while (received < len && millis() - t < 15000) {
    int n = Serial.readBytes((char*)(buf + received), len - received);
    if (n > 0) { received += n; t = millis(); }
  }

  if (received < len) {
    Serial.print("ERR only got ");
    Serial.println(received);
    free(buf);
    return;
  }

  // Play it
  dacPlay(buf, len);
  free(buf);
  Serial.println("DONE");
}
