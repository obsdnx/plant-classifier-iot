// ESP32-CAM (AI-Thinker) live view over the USB cable, no WiFi. Viewer: computer/simple_view.py
// Arduino IDE: Board "AI Thinker ESP32-CAM".
#include "esp_camera.h"

void setup() {
  Serial.begin(921600);
  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0; c.ledc_timer = LEDC_TIMER_0;
  c.pin_d0 = 5;  c.pin_d1 = 18; c.pin_d2 = 19; c.pin_d3 = 21;
  c.pin_d4 = 36; c.pin_d5 = 39; c.pin_d6 = 34; c.pin_d7 = 35;
  c.pin_xclk = 0; c.pin_pclk = 22; c.pin_vsync = 25; c.pin_href = 23;
  c.pin_sccb_sda = 26; c.pin_sccb_scl = 27;
  c.pin_pwdn = 32; c.pin_reset = -1;
  c.xclk_freq_hz = 20000000;
  c.pixel_format = PIXFORMAT_JPEG;
  c.frame_size = FRAMESIZE_QVGA;  // 320x240 keeps it smooth over the cable
  c.jpeg_quality = 12;
  c.fb_count = 2;
  c.fb_location = CAMERA_FB_IN_PSRAM;
  c.grab_mode = CAMERA_GRAB_LATEST;
  if (esp_camera_init(&c) != ESP_OK) { while (true) { Serial.println("CAM_ERROR"); delay(1000); } }
}

void loop() {
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) return;
  Serial.printf("F%u\n", fb->len);
  Serial.write(fb->buf, fb->len);
  esp_camera_fb_return(fb);
}
