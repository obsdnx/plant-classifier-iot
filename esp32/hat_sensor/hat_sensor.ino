// Plant Health Hat - ESP32-S3 + HC-SR04 ultrasonic sensor, readable over WiFi and USB.
// WiFi:  http://hatsensor.local/distance  ->  {"cm": 23.4}   (null = nothing in range)
// USB:   prints "Distance: 23.4 cm" lines at 115200, same as the ultrasonic sketch.
// Works on two boards (hotspot details in wifi_secrets.h):
//   ESP32-S3 (Board "ESP32S3 Dev Module", USB CDC On Boot "Enabled"): Trig -> G1, Echo -> G2, colour LED on pin 48
//   plain ESP32 (Board "ESP32 Dev Module"):                          Trig -> GPIO 5, Echo -> GPIO 18, blue LED on GPIO 2,
//                                                                    speaker on GPIO 25 + GND (1 beep = started, 2 = WiFi on)
// Sensor power: VCC -> 3V3, GND -> GND.
// LED: blinks while connecting, short flash every 3 s when online, fast blinking for 3 s when /blink is called.
#include <WiFi.h>
#include <ESPmDNS.h>
#include <WebServer.h>
#include <HTTPClient.h>
#include "wifi_secrets.h"

#if CONFIG_IDF_TARGET_ESP32S3
const int TRIG = 1;
const int ECHO = 2;
void led(uint8_t r, uint8_t g, uint8_t b) { rgbLedWrite(RGB_BUILTIN, r, g, b); }
#else
const int TRIG = 5;
const int ECHO = 18;
const int BLUE_LED = 2;
const int SPEAKER = 25;  // DAC pin
void led(uint8_t r, uint8_t g, uint8_t b) { digitalWrite(BLUE_LED, (r || g || b) ? HIGH : LOW); }
void tone25(int hz, int ms) {
  long halfUs = 500000L / hz;
  unsigned long end = millis() + ms;
  while (millis() < end) {
    dacWrite(SPEAKER, 255); delayMicroseconds(halfUs);
    dacWrite(SPEAKER, 0);   delayMicroseconds(halfUs);
  }
  dacWrite(SPEAKER, 0);
}
// Downloads 8 kHz unsigned 8-bit mono audio from url and plays it on the DAC speaker.
String playUrl(const String& url) {
  HTTPClient http;
  if (!http.begin(url)) return "bad url";
  int code = http.GET();
  if (code != 200) { http.end(); return "download failed " + String(code); }
  int len = http.getSize();
  if (len <= 0 || len > 8000 * 12) len = 8000 * 12;
  uint8_t* buf = (uint8_t*)malloc(len);
  if (!buf) { http.end(); return "out of memory"; }
  WiFiClient* stream = http.getStreamPtr();
  int got = 0;
  unsigned long deadline = millis() + 15000;
  while (got < len && http.connected() && millis() < deadline) {
    int n = stream->read(buf + got, len - got);
    if (n > 0) got += n; else delay(1);
  }
  http.end();
  // The speaker is wired straight to the pin (no capacitor), so silence must be 0 V:
  // only the upper half of the waveform is played, doubled. A steady mid-level voltage
  // would push constant current through the speaker and brown out the board.
  unsigned long next = micros();
  for (int i = 0; i < got; i++) {
    next += 125;  // 8000 samples per second
    int v = ((int)buf[i] - 128) * 2;
    while ((long)(micros() - next) < 0) {}
    dacWrite(SPEAKER, v > 0 ? (v > 255 ? 255 : v) : 0);
  }
  dacWrite(SPEAKER, 0);
  free(buf);
  return "played " + String(got / 8) + " ms";
}

void beeps(int n, bool rising) {
  for (int i = 0; i < n; i++) { tone25(rising ? 660 + i * 220 : 880, 120); delay(80); }
}
#endif
float distanceCm = -1;
WebServer server(80);
unsigned long blinkUntil = 0;

void updateLed(bool online) {
  unsigned long now = millis();
  if (now < blinkUntil) { led((now / 150) % 2 ? 60 : 0, 0, (now / 150) % 2 ? 60 : 0); return; }
  if (!online) { led(0, 0, (now / 300) % 2 ? 40 : 0); return; }
  led(0, now % 3000 < 120 ? 40 : 0, 0);
}

void sendJson(const String& body) {
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "application/json", body);
}

void setup() {
  Serial.begin(115200);
#ifndef CONFIG_IDF_TARGET_ESP32S3
  pinMode(BLUE_LED, OUTPUT);
  beeps(1, false);
#endif
  pinMode(TRIG, OUTPUT);
  pinMode(ECHO, INPUT);
  digitalWrite(TRIG, LOW);

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  server.on("/distance", [] { sendJson(distanceCm < 0 ? "{\"cm\":null}" : "{\"cm\":" + String(distanceCm, 1) + "}"); });
#ifndef CONFIG_IDF_TARGET_ESP32S3
  server.on("/beep", [] { sendJson("{\"beeping\":true}"); beeps(3, false); });
  server.on("/say", [] {
    String url = server.arg("url");
    String result = playUrl(url);
    Serial.println("SAY " + result);
    sendJson("{\"result\":\"" + result + "\"}");
  });
#endif
  server.on("/blink", [] { blinkUntil = millis() + 3000; sendJson("{\"blinking\":true}"); });
  server.on("/status", [] { sendJson("{\"ip\":\"" + WiFi.localIP().toString() + "\",\"rssi\":" + String(WiFi.RSSI()) + "}"); });
}

void loop() {
  static bool online = false;
  if (!online && WiFi.status() == WL_CONNECTED) {
    online = true;
    MDNS.begin("hatsensor");
    MDNS.addService("http", "tcp", 80);
    server.begin();
    Serial.printf("WIFI_OK ip=%s http://hatsensor.local\n", WiFi.localIP().toString().c_str());
#ifndef CONFIG_IDF_TARGET_ESP32S3
    beeps(2, true);
#endif
  }
  if (online) server.handleClient();
  updateLed(online);
#ifndef CONFIG_IDF_TARGET_ESP32S3
  if (Serial.available()) {  // test over USB: "SAY http://laptop:8000/records/tts/x.raw"
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.startsWith("SAY ")) Serial.println("SAY " + playUrl(line.substring(4)));
  }
#endif

  digitalWrite(TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG, LOW);
  long us = pulseIn(ECHO, HIGH, 30000);
  distanceCm = us == 0 ? -1 : us / 58.0;
  if (distanceCm < 0) Serial.println("No echo");
  else Serial.printf("Distance: %.1f cm\n", distanceCm);
  delay(60);
}
