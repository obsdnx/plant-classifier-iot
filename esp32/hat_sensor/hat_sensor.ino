// Plant Health Hat — ESP32 combined sensor + I2S speaker + WiFi + OTA
// Ultrasonic: Trig -> GPIO 5 | Echo -> GPIO 18
// I2S amp:    BCLK -> GPIO 27 | LRC -> GPIO 14 | DIN -> GPIO 26
// WiFi: connects to hotspot, announces as hatsensor.local
// Endpoints:
//   GET /distance  -> {"cm": 23.4} or {"cm": null}
//   GET /say?url=  -> downloads 8kHz u8 mono audio and plays it
//   GET /beep      -> plays a test beep
//   GET /status    -> {"ip":..., "rssi":...}
// OTA: upload new sketch wirelessly from Arduino IDE after first flash

#include <WiFi.h>
#include <ESPmDNS.h>
#include <WebServer.h>
#include <HTTPClient.h>
#include <ArduinoOTA.h>
#include "driver/i2s.h"
#include <math.h>
#include "wifi_secrets.h"

// ---- pins ----
#define TRIG   5
#define ECHO   18
#define BCLK   27
#define LRC    14
#define DOUT   26
#define RATE   8000

WebServer server(80);
float distanceCm = -1;

// ---- I2S ----
void i2s_setup() {
  i2s_config_t cfg = {};
  cfg.mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX);
  cfg.sample_rate          = RATE;
  cfg.bits_per_sample      = I2S_BITS_PER_SAMPLE_16BIT;
  cfg.channel_format       = I2S_CHANNEL_FMT_RIGHT_LEFT;
  cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  cfg.intr_alloc_flags     = 0;
  cfg.dma_buf_count        = 8;
  cfg.dma_buf_len          = 128;
  cfg.use_apll             = false;
  cfg.tx_desc_auto_clear   = true;
  i2s_driver_install(I2S_NUM_0, &cfg, 0, NULL);
  i2s_pin_config_t pins = {};
  pins.bck_io_num   = BCLK;
  pins.ws_io_num    = LRC;
  pins.data_out_num = DOUT;
  pins.data_in_num  = I2S_PIN_NO_CHANGE;
  i2s_set_pin(I2S_NUM_0, &pins);
}

void i2s_play_u8(const uint8_t* data, size_t len) {
  int16_t buf[64][2];
  size_t written = 0;
  while (written < len) {
    int chunk = min((size_t)64, len - written);
    for (int i = 0; i < chunk; i++) {
      int16_t s = ((int16_t)data[written + i] - 128) * 256;
      buf[i][0] = s;
      buf[i][1] = s;
    }
    size_t out = 0;
    i2s_write(I2S_NUM_0, buf, chunk * 4, &out, portMAX_DELAY);
    written += chunk;
  }
}

void playTone(int hz, int ms) {
  int n = RATE * ms / 1000;
  int16_t buf[64][2];
  int written = 0;
  while (written < n) {
    int chunk = min(64, n - written);
    for (int i = 0; i < chunk; i++) {
      int16_t s = (int16_t)(sinf(2.0f * M_PI * hz * (written + i) / (float)RATE) * 20000.0f);
      buf[i][0] = s; buf[i][1] = s;
    }
    size_t out = 0;
    i2s_write(I2S_NUM_0, buf, chunk * 4, &out, portMAX_DELAY);
    written += chunk;
  }
}

String playUrl(const String& url) {
  HTTPClient http;
  if (!http.begin(url)) return "bad url";
  int code = http.GET();
  if (code != 200) { http.end(); return "download failed " + String(code); }
  int len = http.getSize();
  if (len <= 0 || len > RATE * 12) len = RATE * 12;
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
  i2s_play_u8(buf, got);
  free(buf);
  return "played " + String(got / RATE * 1000) + " ms";
}

// ---- HTTP helpers ----
void sendJson(const String& body) {
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "application/json", body);
}

// ---- setup ----
void setup() {
  Serial.begin(115200);
  delay(500);

  // Ultrasonic
  pinMode(TRIG, OUTPUT);
  pinMode(ECHO, INPUT);
  digitalWrite(TRIG, LOW);

  // I2S
  i2s_setup();
  playTone(880, 200);  // boot beep

  // WiFi
  Serial.print("Connecting to ");
  Serial.println(WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) {
    delay(300);
    Serial.print(".");
  }
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\nWiFi failed — continuing without network");
  } else {
    Serial.println("\nWiFi OK: " + WiFi.localIP().toString());
    playTone(660, 150); delay(80); playTone(880, 150);  // 2-beep = wifi ok
  }

  // mDNS
  MDNS.begin("hatsensor");
  MDNS.addService("http", "tcp", 80);

  // OTA
  ArduinoOTA.setHostname("hatsensor");
  ArduinoOTA.begin();

  // Routes
  server.on("/distance", [] {
    sendJson(distanceCm < 0 ? "{\"cm\":null}" : "{\"cm\":" + String(distanceCm, 1) + "}");
  });
  server.on("/say", [] {
    String url = server.arg("url");
    if (url.isEmpty()) { server.send(400, "text/plain", "missing url"); return; }
    String result = playUrl(url);
    Serial.println("SAY " + result);
    sendJson("{\"result\":\"" + result + "\"}");
  });
  server.on("/beep", [] {
    playTone(880, 300);
    sendJson("{\"ok\":true}");
  });
  server.on("/status", [] {
    sendJson("{\"ip\":\"" + WiFi.localIP().toString() + "\",\"rssi\":" + String(WiFi.RSSI()) + "}");
  });
  server.begin();
  Serial.println("HTTP server started — http://hatsensor.local");
}

// ---- loop ----
void loop() {
  ArduinoOTA.handle();
  server.handleClient();

  // Ultrasonic reading
  digitalWrite(TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG, LOW);
  long us = pulseIn(ECHO, HIGH, 30000);
  distanceCm = (us == 0) ? -1 : us / 58.0;

  if (distanceCm < 0) Serial.println("No echo");
  else Serial.printf("Distance: %.1f cm\n", distanceCm);

  delay(60);
}
