// OV7670 (no FIFO) live view over USB on ESP32-S3. No WiFi.
// Viewer on laptop: computer/simple_view.py
// Arduino IDE: Board "ESP32S3 Dev Module", USB CDC On Boot "Enabled", PSRAM "Disabled"
// (PSRAM must stay disabled: D7/D5/D3 use GPIO 35/36/37, which PSRAM would take over.)
#include "esp_camera.h"

void setup() {
  Serial.begin(115200);
  delay(3000);

  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0; c.ledc_timer = LEDC_TIMER_0;
  c.pin_sccb_sda = 5;  c.pin_sccb_scl = 4;
  c.pin_vsync = 6;     c.pin_href = 7;     c.pin_pclk = 13;  c.pin_xclk = 12;
  c.pin_d0 = 42; c.pin_d1 = 38; c.pin_d2 = 41; c.pin_d3 = 37;
  c.pin_d4 = 40; c.pin_d5 = 36; c.pin_d6 = 39; c.pin_d7 = 35;
  c.pin_pwdn = -1; c.pin_reset = -1;
  c.xclk_freq_hz = 10000000;
  c.pixel_format = PIXFORMAT_YUV422;  // OV7670 can't make JPEG; laptop decodes YUYV
  c.frame_size = FRAMESIZE_QVGA;      // 320x240
  c.fb_count = 1;
  c.fb_location = CAMERA_FB_IN_DRAM;
  c.grab_mode = CAMERA_GRAB_WHEN_EMPTY;

  esp_err_t err = esp_camera_init(&c);
  while (err != ESP_OK) {
    Serial.printf("CAM_ERROR 0x%x (%s)\n", err, esp_err_to_name(err));
    delay(2000);
  }
  Serial.printf("CAM_OK PID=0x%x\n", esp_camera_sensor_get()->id.PID);
}

extern "C" {
  uint8_t SCCB_Read(uint8_t slv_addr, uint8_t reg);
  int SCCB_Write(uint8_t slv_addr, uint8_t reg, uint8_t data);
}
const uint8_t OV7670_ADDR = 0x21;

// "W 13 E7" writes camera register 0x13 = 0xE7; "R 13" reads it (hex, no 0x)
void handleCommand() {
  while (Serial.available()) {
  String cmd = Serial.readStringUntil('\n');
  char op = 0; unsigned reg = 0, val = 0;
  int n = sscanf(cmd.c_str(), " %c %x %x", &op, &reg, &val);
  if (n == 3 && (op == 'W' || op == 'w')) SCCB_Write(OV7670_ADDR, reg, val);
  if (n >= 2) Serial.printf("VAL %02X=%02X\n", reg, SCCB_Read(OV7670_ADDR, reg));
  }
}

void loop() {
  handleCommand();
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) { Serial.println("NO_FRAME"); delay(500); return; }
  Serial.printf("R%u %u %u\n", fb->width, fb->height, fb->len);
  Serial.write(fb->buf, fb->len);
  esp_camera_fb_return(fb);
}
