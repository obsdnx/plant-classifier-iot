// Plant Health Hat - ESP32-CAM (AI-Thinker) with HC-SR04 ultrasonic sensor, over WiFi.
// The laptop server polls http://hatcam.local/distance and fetches http://hatcam.local/capture.
// Live view: http://hatcam.local:81/stream
// Arduino IDE: Board "AI Thinker ESP32-CAM". Put hotspot name/password in wifi_secrets.h.
// Sensor wiring: VCC -> 3V3, GND -> GND, Trig -> IO13, Echo -> IO14.
// Power when USB is unplugged: 5V -> 5V pin, GND -> GND pin (do NOT use 3.3V pin).
#include "esp_camera.h"
#include <WiFi.h>
#include <ESPmDNS.h>
#include <ArduinoOTA.h>
#include "esp_http_server.h"
#include "esp_task_wdt.h"
#include "wifi_secrets.h"

#define WIFI_TIMEOUT_MS 20000   // restart if WiFi not up in 20 s
#define WDT_TIMEOUT_S   10      // watchdog: restart if loop stalls 10 s

#define PWDN_GPIO_NUM  32
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM   0
#define SIOD_GPIO_NUM  26
#define SIOC_GPIO_NUM  27
#define Y9_GPIO_NUM    35
#define Y8_GPIO_NUM    34
#define Y7_GPIO_NUM    39
#define Y6_GPIO_NUM    36
#define Y5_GPIO_NUM    21
#define Y4_GPIO_NUM    19
#define Y3_GPIO_NUM    18
#define Y2_GPIO_NUM     5
#define VSYNC_GPIO_NUM 25
#define HREF_GPIO_NUM  23
#define PCLK_GPIO_NUM  22

const int TRIG = 13;
const int ECHO = 14;
volatile float distanceCm = -1;  // -1 = no echo
const int RED_LED = 33;           // small red LED on the back, LOW = on
volatile unsigned long blinkUntil = 0;

#define BOUNDARY "hatcamframe"

static esp_err_t distance_handler(httpd_req_t* req) {
  char buf[64];
  if (distanceCm < 0) snprintf(buf, sizeof(buf), "{\"cm\":null}");
  else snprintf(buf, sizeof(buf), "{\"cm\":%.1f}", distanceCm);
  httpd_resp_set_type(req, "application/json");
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  return httpd_resp_sendstr(req, buf);
}

static esp_err_t capture_handler(httpd_req_t* req) {
  camera_fb_t* fb = esp_camera_fb_get();
  if (fb) esp_camera_fb_return(fb);  // drop the buffered frame so the photo is fresh
  fb = esp_camera_fb_get();
  if (!fb) { httpd_resp_send_500(req); return ESP_FAIL; }
  httpd_resp_set_type(req, "image/jpeg");
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  esp_err_t res = httpd_resp_send(req, (const char*)fb->buf, fb->len);
  esp_camera_fb_return(fb);
  return res;
}

static esp_err_t blink_handler(httpd_req_t* req) {
  blinkUntil = millis() + 3000;
  httpd_resp_set_type(req, "application/json");
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  return httpd_resp_sendstr(req, "{\"blinking\":true}");
}

static esp_err_t status_handler(httpd_req_t* req) {
  char buf[128];
  snprintf(buf, sizeof(buf), "{\"ip\":\"%s\",\"rssi\":%d,\"psram\":%d}",
           WiFi.localIP().toString().c_str(), WiFi.RSSI(), psramFound());
  httpd_resp_set_type(req, "application/json");
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  return httpd_resp_sendstr(req, buf);
}

static esp_err_t stream_handler(httpd_req_t* req) {
  char part[80];
  httpd_resp_set_type(req, "multipart/x-mixed-replace;boundary=" BOUNDARY);
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  while (true) {
    esp_task_wdt_reset();  // keep watchdog happy during streaming
    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) return ESP_FAIL;
    size_t n = snprintf(part, sizeof(part), "\r\n--" BOUNDARY "\r\nContent-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n", fb->len);
    esp_err_t res = httpd_resp_send_chunk(req, part, n);
    if (res == ESP_OK) res = httpd_resp_send_chunk(req, (const char*)fb->buf, fb->len);
    esp_camera_fb_return(fb);
    if (res != ESP_OK) return res;
  }
}

void startServers() {
  httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
  httpd_handle_t api = NULL;
  if (httpd_start(&api, &cfg) == ESP_OK) {
    httpd_uri_t d = {"/distance", HTTP_GET, distance_handler, NULL};
    httpd_uri_t c = {"/capture", HTTP_GET, capture_handler, NULL};
    httpd_uri_t s = {"/status", HTTP_GET, status_handler, NULL};
    httpd_uri_t b = {"/blink", HTTP_GET, blink_handler, NULL};
    httpd_register_uri_handler(api, &b);
    httpd_register_uri_handler(api, &d);
    httpd_register_uri_handler(api, &c);
    httpd_register_uri_handler(api, &s);
  }
  cfg.server_port = 81;
  cfg.ctrl_port = 32769;
  httpd_handle_t stream = NULL;
  if (httpd_start(&stream, &cfg) == ESP_OK) {
    httpd_uri_t st = {"/stream", HTTP_GET, stream_handler, NULL};
    httpd_register_uri_handler(stream, &st);
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(RED_LED, OUTPUT);
  digitalWrite(RED_LED, HIGH);
  pinMode(TRIG, OUTPUT);
  pinMode(ECHO, INPUT);
  digitalWrite(TRIG, LOW);

  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0; c.ledc_timer = LEDC_TIMER_0;
  c.pin_d0 = Y2_GPIO_NUM; c.pin_d1 = Y3_GPIO_NUM; c.pin_d2 = Y4_GPIO_NUM; c.pin_d3 = Y5_GPIO_NUM;
  c.pin_d4 = Y6_GPIO_NUM; c.pin_d5 = Y7_GPIO_NUM; c.pin_d6 = Y8_GPIO_NUM; c.pin_d7 = Y9_GPIO_NUM;
  c.pin_xclk = XCLK_GPIO_NUM; c.pin_pclk = PCLK_GPIO_NUM; c.pin_vsync = VSYNC_GPIO_NUM; c.pin_href = HREF_GPIO_NUM;
  c.pin_sccb_sda = SIOD_GPIO_NUM; c.pin_sccb_scl = SIOC_GPIO_NUM;
  c.pin_pwdn = PWDN_GPIO_NUM; c.pin_reset = RESET_GPIO_NUM;
  c.xclk_freq_hz = 20000000;
  c.pixel_format = PIXFORMAT_JPEG;
  c.frame_size = FRAMESIZE_VGA;
  c.jpeg_quality = 12;
  c.fb_count = psramFound() ? 2 : 1;
  c.fb_location = psramFound() ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;
  c.grab_mode = CAMERA_GRAB_LATEST;
  esp_err_t err = esp_camera_init(&c);
  if (err != ESP_OK) Serial.printf("CAM_ERROR 0x%x\n", err);
  else Serial.println("CAM_OK");

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.printf("Connecting to WiFi \"%s\"", WIFI_SSID);
  unsigned long wifiStart = millis();
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - wifiStart > WIFI_TIMEOUT_MS) {
      Serial.println("\nWIFI_TIMEOUT — restarting in 3 s");
      delay(3000);
      ESP.restart();
    }
    delay(500); Serial.print(".");
  }
  Serial.printf("\nWIFI_OK ip=%s\n", WiFi.localIP().toString().c_str());
  if (MDNS.begin("hatcam")) {
    MDNS.addService("http", "tcp", 80);
    Serial.println("MDNS_OK http://hatcam.local");
  }
  startServers();

  // OTA — upload new sketches wirelessly from Arduino IDE
  ArduinoOTA.setHostname("hatcam");
  ArduinoOTA.begin();
  Serial.println("OTA ready");

  // Watchdog: restart board if it hangs for WDT_TIMEOUT_S seconds
  esp_task_wdt_config_t wdt_cfg = { .timeout_ms = WDT_TIMEOUT_S * 1000, .idle_core_mask = 0, .trigger_panic = true };
  esp_task_wdt_init(&wdt_cfg);
  esp_task_wdt_add(NULL);
}

void loop() {
  esp_task_wdt_reset();
  ArduinoOTA.handle();

  digitalWrite(TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG, LOW);
  long us = pulseIn(ECHO, HIGH, 30000);
  distanceCm = us == 0 ? -1 : us / 58.0;

  // Auto-reconnect if WiFi drops
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WIFI_LOST — reconnecting...");
    WiFi.reconnect();
    unsigned long t = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - t < WIFI_TIMEOUT_MS) {
      delay(500); esp_task_wdt_reset();
    }
    if (WiFi.status() != WL_CONNECTED) { delay(1000); ESP.restart(); }
    Serial.printf("WIFI_BACK ip=%s\n", WiFi.localIP().toString().c_str());
  }

  unsigned long now = millis();
  if (now < blinkUntil) digitalWrite(RED_LED, (now / 150) % 2 ? LOW : HIGH);
  else digitalWrite(RED_LED, now % 3000 < 120 ? LOW : HIGH);  // short heartbeat flash = online
  delay(80);
}
