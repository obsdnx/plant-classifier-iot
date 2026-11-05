/*
  Plant Health Classifier — ESP32-CAM client
  Board: AI Thinker ESP32-CAM

  Wiring:
    - Flash button (GPIO 0) already on board — press to classify
    - Serial monitor at 115200 baud shows results

  Libraries needed (install via Arduino Library Manager):
    - ESP32 board package: https://dl.espressif.com/dl/package_esp32_index.json
    - ArduinoJson  (by Benoit Blanchon)

  Board settings in Arduino IDE:
    Board:           AI Thinker ESP32-CAM
    Partition Scheme: Huge APP (3MB No OTA)
    Port:            your COM/tty port
*/

#include "esp_camera.h"
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// ── CONFIG — edit these ────────────────────────────────────────────────────────
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* SERVER_IP     = "192.168.1.100";   // your computer's local IP
const int   SERVER_PORT   = 8000;
// ──────────────────────────────────────────────────────────────────────────────

#define BUTTON_PIN 0   // GPIO0 = built-in flash button on AI Thinker

// AI Thinker ESP32-CAM pin map
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

bool cameraReady = false;

void setup() {
  Serial.begin(115200);
  pinMode(BUTTON_PIN, INPUT_PULLUP);

  Serial.println("\nPlant Health Classifier — ESP32-CAM");
  Serial.println("Connecting to WiFi...");

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  int tries = 0;
  while (WiFi.status() != WL_CONNECTED && tries < 30) {
    delay(500);
    Serial.print(".");
    tries++;
  }

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\nERROR: WiFi failed. Check SSID/password.");
    return;
  }

  Serial.println("\nWiFi connected: " + WiFi.localIP().toString());
  initCamera();
  Serial.println("Ready. Press the flash button (GPIO 0) to classify a leaf.");
}

void loop() {
  if (digitalRead(BUTTON_PIN) == LOW) {
    delay(50);  // debounce
    if (digitalRead(BUTTON_PIN) == LOW) {
      classifyLeaf();
      while (digitalRead(BUTTON_PIN) == LOW) delay(10);  // wait for release
    }
  }
}

void initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0       = Y2_GPIO_NUM;
  config.pin_d1       = Y3_GPIO_NUM;
  config.pin_d2       = Y4_GPIO_NUM;
  config.pin_d3       = Y5_GPIO_NUM;
  config.pin_d4       = Y6_GPIO_NUM;
  config.pin_d5       = Y7_GPIO_NUM;
  config.pin_d6       = Y8_GPIO_NUM;
  config.pin_d7       = Y9_GPIO_NUM;
  config.pin_xclk     = XCLK_GPIO_NUM;
  config.pin_pclk     = PCLK_GPIO_NUM;
  config.pin_vsync    = VSYNC_GPIO_NUM;
  config.pin_href     = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn     = PWDN_GPIO_NUM;
  config.pin_reset    = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size   = FRAMESIZE_SVGA;   // 800x600 — good quality, not too big
  config.jpeg_quality = 10;               // 0=best, 63=worst
  config.fb_count     = 1;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed: 0x%x\n", err);
    return;
  }

  // Improve image quality
  sensor_t* s = esp_camera_sensor_get();
  s->set_brightness(s, 0);
  s->set_contrast(s, 0);
  s->set_saturation(s, 0);
  s->set_sharpness(s, 0);
  s->set_whitebal(s, 1);
  s->set_awb_gain(s, 1);
  s->set_wb_mode(s, 0);
  s->set_exposure_ctrl(s, 1);
  s->set_aec2(s, 0);
  s->set_gain_ctrl(s, 1);
  s->set_agc_gain(s, 0);

  cameraReady = true;
  Serial.println("Camera ready.");
}

void classifyLeaf() {
  if (!cameraReady) {
    Serial.println("Camera not ready.");
    return;
  }

  Serial.println("\nCapturing photo...");
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("ERROR: Camera capture failed.");
    return;
  }

  Serial.printf("Photo captured: %d bytes\n", fb->len);
  Serial.println("Sending to server...");

  String url = "http://" + String(SERVER_IP) + ":" + String(SERVER_PORT) + "/classify";

  HTTPClient http;
  http.begin(url);
  http.setTimeout(30000);

  // Build multipart/form-data body manually
  String boundary = "----ESP32Boundary";
  String header = "--" + boundary + "\r\n"
                  "Content-Disposition: form-data; name=\"image\"; filename=\"leaf.jpg\"\r\n"
                  "Content-Type: image/jpeg\r\n\r\n";
  String footer = "\r\n--" + boundary + "--\r\n";

  int totalLen = header.length() + fb->len + footer.length();

  http.addHeader("Content-Type", "multipart/form-data; boundary=" + boundary);
  http.addHeader("Content-Length", String(totalLen));

  // Combine into one buffer
  uint8_t* body = (uint8_t*)malloc(totalLen);
  if (!body) {
    Serial.println("ERROR: Out of memory.");
    esp_camera_fb_return(fb);
    return;
  }

  memcpy(body, header.c_str(), header.length());
  memcpy(body + header.length(), fb->buf, fb->len);
  memcpy(body + header.length() + fb->len, footer.c_str(), footer.length());

  esp_camera_fb_return(fb);

  int httpCode = http.POST(body, totalLen);
  free(body);

  if (httpCode == 200) {
    String response = http.getString();
    http.end();
    parseAndPrint(response);
  } else {
    Serial.printf("ERROR: Server returned %d\n", httpCode);
    if (httpCode > 0) Serial.println(http.getString());
    else Serial.println("Cannot reach server — check IP and WiFi.");
    http.end();
  }
}

void parseAndPrint(const String& json) {
  StaticJsonDocument<2048> doc;
  DeserializationError err = deserializeJson(doc, json);
  if (err) {
    Serial.println("ERROR: Could not parse response.");
    Serial.println(json);
    return;
  }

  const char* status      = doc["status"]      | "error";
  const char* label       = doc["label"]       | "unknown";
  float       confidence  = doc["confidence"]  | 0.0f;
  const char* explanation = doc["explanation"] | "";

  Serial.println("\n========================================");
  if (strcmp(status, "ok") == 0) {
    Serial.printf("RESULT:  %s\n", label);
    Serial.printf("CONFIDENCE: %.0f%%\n", confidence * 100);
    Serial.printf("\n%s\n", explanation);
  } else if (strcmp(status, "unsure") == 0) {
    Serial.printf("UNSURE (%.0f%%): %s\n", confidence * 100, explanation);
  } else {
    Serial.printf("ERROR: %s\n", explanation);
  }
  Serial.println("========================================\n");
}
