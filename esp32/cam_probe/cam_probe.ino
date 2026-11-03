#include "esp_camera.h"

struct Pins { const char* name; int xclk, sda, scl, y9, y8, y7, y6, y5, y4, y3, y2, vsync, href, pclk; };

Pins boards[] = {
  {"ESP32S3_EYE / Freenove / Goouuu", 15, 4, 5, 16, 17, 18, 12, 10, 8, 9, 11, 6, 7, 13},
  {"XIAO_ESP32S3",                    10, 40, 39, 48, 11, 12, 14, 16, 18, 17, 15, 38, 47, 13},
  {"ESP32S3_CAM_LCD",                 40, 17, 18, 39, 41, 42, 12, 3, 14, 47, 13, 21, 38, 11},
  {"DFRobot FireBeetle2 S3",          45, 1, 2, 48, 46, 8, 7, 4, 41, 40, 39, 6, 42, 5},
};
int clocks[] = {20000000, 10000000};

String result = "NO CAMERA FOUND with any layout";

bool tryInit(Pins& p, int xclk) {
  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0; c.ledc_timer = LEDC_TIMER_0;
  c.pin_pwdn = -1; c.pin_reset = -1; c.pin_xclk = p.xclk;
  c.pin_sccb_sda = p.sda; c.pin_sccb_scl = p.scl;
  c.pin_d7 = p.y9; c.pin_d6 = p.y8; c.pin_d5 = p.y7; c.pin_d4 = p.y6;
  c.pin_d3 = p.y5; c.pin_d2 = p.y4; c.pin_d1 = p.y3; c.pin_d0 = p.y2;
  c.pin_vsync = p.vsync; c.pin_href = p.href; c.pin_pclk = p.pclk;
  c.xclk_freq_hz = xclk; c.pixel_format = PIXFORMAT_JPEG;
  c.frame_size = FRAMESIZE_QVGA; c.jpeg_quality = 15; c.fb_count = 1;
  c.fb_location = CAMERA_FB_IN_PSRAM; c.grab_mode = CAMERA_GRAB_LATEST;
  esp_err_t err = esp_camera_init(&c);
  Serial.printf("  %-34s xclk=%2dMHz -> %s\n", p.name, xclk / 1000000, esp_err_to_name(err));
  if (err != ESP_OK) { esp_camera_deinit(); return false; }
  sensor_t* s = esp_camera_sensor_get();
  result = String("FOUND: ") + p.name + " at " + (xclk / 1000000) + "MHz, sensor PID=0x" + String(s->id.PID, HEX);
  esp_camera_deinit();
  return true;
}

void setup() {
  Serial.begin(115200);
  delay(4000);
  Serial.printf("PROBE START psram=%d\n", psramFound());
  for (auto& p : boards)
    for (int xclk : clocks)
      if (tryInit(p, xclk)) goto done;
done:
  Serial.println("PROBE DONE");
}

void loop() {
  Serial.println("RESULT: " + result);
  delay(2000);
}
