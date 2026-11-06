/*
  Plant Health Classifier — ESP32-S3-CAM via USB Serial

  Arduino IDE board settings:
    Board:              ESP32S3 Dev Module
    PSRAM:              OPI PSRAM
    Flash Size:         16MB (or 8MB depending on your board)
    Partition Scheme:   Huge APP (3MB No OTA/1MB SPIFFS)
    USB CDC On Boot:    Disabled
    Upload Speed:       460800

  To flash:
    1. Hold the BOOT button on the board
    2. Click Upload
    3. Release BOOT when you see "Connecting....." in the output

  Pin definitions below are for the common ESP32-S3-CAM (Freenove style).
  If the camera fails to init, check your board's datasheet for the correct pins.
*/

#include "esp_camera.h"

// ── Camera pins — ESP32-S3-CAM (Freenove / common module) ─────────────────────
#define PWDN_GPIO_NUM    -1
#define RESET_GPIO_NUM   -1
#define XCLK_GPIO_NUM    15
#define SIOD_GPIO_NUM     4
#define SIOC_GPIO_NUM     5
#define Y9_GPIO_NUM      16
#define Y8_GPIO_NUM      17
#define Y7_GPIO_NUM      18
#define Y6_GPIO_NUM      12
#define Y5_GPIO_NUM      10
#define Y4_GPIO_NUM       8
#define Y3_GPIO_NUM       9
#define Y2_GPIO_NUM      11
#define VSYNC_GPIO_NUM    6
#define HREF_GPIO_NUM     7
#define PCLK_GPIO_NUM    13

#define BUTTON_PIN 0   // BOOT button doubles as trigger

bool cameraReady = false;

void setup() {
  Serial.begin(460800);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  initCamera();
  Serial.println("READY");
}

void loop() {
  if (digitalRead(BUTTON_PIN) == LOW) {
    delay(50);
    if (digitalRead(BUTTON_PIN) == LOW) {
      sendPhoto();
      while (digitalRead(BUTTON_PIN) == LOW) delay(10);
    }
  }

  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd == "CAPTURE") sendPhoto();
  }
}

void initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM; config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM; config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM; config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM; config.pin_d7 = Y9_GPIO_NUM;
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
  config.frame_size   = FRAMESIZE_SVGA;
  config.jpeg_quality = 12;
  config.fb_count     = 1;
  config.grab_mode    = CAMERA_GRAB_WHEN_EMPTY;
  config.fb_location  = CAMERA_FB_IN_PSRAM;

  if (esp_camera_init(&config) != ESP_OK) {
    Serial.println("ERROR:Camera init failed - check pin definitions for your board");
    return;
  }
  cameraReady = true;
}

void sendPhoto() {
  if (!cameraReady) { Serial.println("ERROR:Camera not ready"); return; }

  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) { Serial.println("ERROR:Capture failed"); return; }

  Serial.printf("IMG:%d\n", fb->len);
  Serial.write(fb->buf, fb->len);
  Serial.flush();

  esp_camera_fb_return(fb);
}
