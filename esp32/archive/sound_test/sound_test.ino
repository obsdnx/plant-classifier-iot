// MAX98357A I2S audio over USB serial.
// Plays a boot beep on startup, then waits for audio from speak_serial.py.
// Wiring: BCLK -> GPIO 32 | LRC -> GPIO 26 | DIN -> GPIO 33
//         Vin  -> 5V      | GND -> GND      | SD  -> floating
// Protocol: 0xAA 0xBB + 4-byte LE length + raw 8-bit unsigned 8kHz mono audio
// Responses: "READY", "RECV <n>", "PLAY", "DONE"

#include "driver/i2s.h"
#include <math.h>

#define BCLK    27
#define LRC    14
#define DIN_PIN 26
#define RATE    8000
#define BAUD    115200
#define MAX_AUDIO (RATE * 12)

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
  pins.data_out_num = DIN_PIN;
  pins.data_in_num  = I2S_PIN_NO_CHANGE;
  i2s_set_pin(I2S_NUM_0, &pins);
}

void playTone(int hz, int ms) {
  int samples = RATE * ms / 1000;
  int16_t buf[64][2];
  int written = 0;
  while (written < samples) {
    int chunk = min(64, samples - written);
    for (int i = 0; i < chunk; i++) {
      int16_t s = (int16_t)(sinf(2.0f * M_PI * hz * (written + i) / (float)RATE) * 20000.0f);
      buf[i][0] = s;
      buf[i][1] = s;
    }
    size_t out = 0;
    i2s_write(I2S_NUM_0, buf, chunk * 4, &out, portMAX_DELAY);
    written += chunk;
  }
}

void playAudio(uint8_t* data, uint32_t len) {
  int16_t buf[64][2];
  uint32_t written = 0;
  while (written < len) {
    int chunk = min((uint32_t)64, len - written);
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

void setup() {
  Serial.begin(BAUD);
  delay(500);

  i2s_setup();

  // Boot beep: confirms wiring works
  playTone(880, 200);

  Serial.println("READY");
}

void loop() {
  if (Serial.available() < 2) return;

  uint8_t b0 = Serial.read();
  if (b0 != 0xAA) return;

  unsigned long t = millis();
  while (!Serial.available() && millis() - t < 100) {}
  if (!Serial.available()) return;
  uint8_t b1 = Serial.read();
  if (b1 != 0xBB) return;

  while (Serial.available() < 4) {}
  uint32_t len = 0;
  Serial.readBytes((char*)&len, 4);

  if (len == 0 || len > (uint32_t)MAX_AUDIO) {
    Serial.printf("BAD_LEN %u\n", len);
    return;
  }

  uint8_t* buf = (uint8_t*)malloc(len);
  if (!buf) { Serial.println("OOM"); return; }

  Serial.printf("RECV %u\n", len);

  uint32_t got = 0;
  unsigned long deadline = millis() + 20000;
  while (got < len && millis() < deadline) {
    int n = Serial.readBytes((char*)buf + got, len - got);
    if (n > 0) got += n;
  }

  Serial.println("PLAY");
  playAudio(buf, got);
  free(buf);
  Serial.println("DONE");
}
