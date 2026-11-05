// ESP32 I2S sound test — beeps through I2S amp (MAX98357 etc)
// DIN=32  BCLK=35  LRC=34

#include <driver/i2s.h>
#include <math.h>

#define I2S_DOUT 32
#define I2S_BCLK 35
#define I2S_LRC  34

#define SAMPLE_RATE 22050
#define AMPLITUDE   28000

void i2s_init() {
  i2s_config_t cfg = {
    .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate          = SAMPLE_RATE,
    .bits_per_sample      = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format       = I2S_CHANNEL_FMT_RIGHT_LEFT,
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count        = 8,
    .dma_buf_len          = 64,
    .use_apll             = false,
    .tx_desc_auto_clear   = true,
  };
  i2s_pin_config_t pins = {
    .bck_io_num   = I2S_BCLK,
    .ws_io_num    = I2S_LRC,
    .data_out_num = I2S_DOUT,
    .data_in_num  = I2S_PIN_NO_CHANGE,
  };
  i2s_driver_install(I2S_NUM_0, &cfg, 0, NULL);
  i2s_set_pin(I2S_NUM_0, &pins);
}

void play_tone(int freq, int duration_ms) {
  int samples = SAMPLE_RATE * duration_ms / 1000;
  int16_t buf[256];
  size_t written;
  int i = 0;
  while (i < samples) {
    int chunk = min(128, samples - i);
    for (int j = 0; j < chunk; j++) {
      int16_t s = (int16_t)(AMPLITUDE * sin(2.0 * M_PI * freq * (i + j) / SAMPLE_RATE));
      buf[j * 2]     = s;  // left
      buf[j * 2 + 1] = s;  // right
    }
    i2s_write(I2S_NUM_0, buf, chunk * 4, &written, portMAX_DELAY);
    i += chunk;
  }
}

void silence(int duration_ms) {
  int samples = SAMPLE_RATE * duration_ms / 1000;
  int16_t buf[256] = {0};
  size_t written;
  int remaining = samples * 4;
  while (remaining > 0) {
    int chunk = min((int)sizeof(buf), remaining);
    i2s_write(I2S_NUM_0, buf, chunk, &written, portMAX_DELAY);
    remaining -= written;
  }
}

void setup() {
  i2s_init();
}

void loop() {
  // Ascending sweep
  for (int f = 400; f <= 1600; f += 200) {
    play_tone(f, 100);
  }
  silence(300);

  // Two beeps
  play_tone(1000, 150);
  silence(100);
  play_tone(1000, 150);
  silence(800);
}
