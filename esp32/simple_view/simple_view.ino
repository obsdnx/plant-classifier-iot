#include "esp_camera.h"

#define PWDN_GPIO_NUM  -1
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM  15
#define SIOD_GPIO_NUM   4
#define SIOC_GPIO_NUM   5
#define Y9_GPIO_NUM    16
#define Y8_GPIO_NUM    17
#define Y7_GPIO_NUM    18
#define Y6_GPIO_NUM    12
#define Y5_GPIO_NUM    10
#define Y4_GPIO_NUM     8
#define Y3_GPIO_NUM     9
#define Y2_GPIO_NUM    11
#define VSYNC_GPIO_NUM  6
#define HREF_GPIO_NUM   7
#define PCLK_GPIO_NUM  13

void setup() {
  Serial.begin(460800);
  camera_config_t cfg;
  cfg.ledc_channel = LEDC_CHANNEL_0; cfg.ledc_timer = LEDC_TIMER_0;
  cfg.pin_d0=Y2_GPIO_NUM; cfg.pin_d1=Y3_GPIO_NUM; cfg.pin_d2=Y4_GPIO_NUM;
  cfg.pin_d3=Y5_GPIO_NUM; cfg.pin_d4=Y6_GPIO_NUM; cfg.pin_d5=Y7_GPIO_NUM;
  cfg.pin_d6=Y8_GPIO_NUM; cfg.pin_d7=Y9_GPIO_NUM;
  cfg.pin_xclk=XCLK_GPIO_NUM; cfg.pin_pclk=PCLK_GPIO_NUM;
  cfg.pin_vsync=VSYNC_GPIO_NUM; cfg.pin_href=HREF_GPIO_NUM;
  cfg.pin_sscb_sda=SIOD_GPIO_NUM; cfg.pin_sscb_scl=SIOC_GPIO_NUM;
  cfg.pin_pwdn=PWDN_GPIO_NUM; cfg.pin_reset=RESET_GPIO_NUM;
  cfg.xclk_freq_hz=20000000; cfg.pixel_format=PIXFORMAT_JPEG;
  cfg.frame_size=FRAMESIZE_QVGA; cfg.jpeg_quality=15;
  cfg.fb_count=2; cfg.grab_mode=CAMERA_GRAB_LATEST;
  cfg.fb_location=CAMERA_FB_IN_PSRAM;
  esp_err_t err = esp_camera_init(&cfg);
  while (err != ESP_OK) {
    Serial.printf("CAM_ERROR 0x%x psram=%d\n", err, psramFound());
    delay(1000);
  }
  Serial.println("CAM_OK");
}

void loop() {
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) { Serial.println("NO_FRAME"); delay(500); return; }
  Serial.printf("F%d\n", fb->len);
  Serial.write(fb->buf, fb->len);
  esp_camera_fb_return(fb);
}
