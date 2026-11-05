// ESP32 + MAX98357A I2S sound test
// BCLK=32  DIN=33  LRC=35

#include <driver/i2s.h>
#include <math.h>

#define I2S_DOUT  33
#define I2S_BCLK  32
#define I2S_LRC   35

#define SAMPLE_RATE 16000
#define AMPLITUDE   30000

void i2s_init() {
  i2s_config_t cfg = {
    .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
    .sample_rate          = SAMPLE_RATE,
    .bits_per_sample      = I2S_BITS_PER_SAMPLE_16BIT,
    .channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT,
    // compatible with both old and new ESP32 Arduino cores
    .communication_format = (i2s_comm_format_t)(I2S_COMM_FORMAT_I2S | I2S_COMM_FORMAT_I2S_MSB),
    .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count        = 8,
    .dma_buf_len          = 128,
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
  i2s_zero_dma_buffer(I2S_NUM_0);
}

void play_tone(int freq, int ms) {
  int total = SAMPLE_RATE * ms / 1000;
  int16_t buf[128];
  size_t written;
  int sent = 0;
  while (sent < total) {
    int n = min(128, total - sent);
    for (int i = 0; i < n; i++) {
      buf[i] = (int16_t)(AMPLITUDE * sin(2.0 * M_PI * freq * (sent + i) / SAMPLE_RATE));
    }
    i2s_write(I2S_NUM_0, buf, n * sizeof(int16_t), &written, portMAX_DELAY);
    sent += n;
  }
}

void silence(int ms) {
  int16_t buf[128] = {};
  size_t written;
  int total = SAMPLE_RATE * ms / 1000 * sizeof(int16_t);
  int sent = 0;
  while (sent < total) {
    int n = min((int)sizeof(buf), total - sent);
    i2s_write(I2S_NUM_0, buf, n, &written, portMAX_DELAY);
    sent += written;
  }
}

void setup() {
  Serial.begin(115200);
  i2s_init();
  Serial.println("I2S ready");
}

void loop() {
  Serial.println("440Hz");
  play_tone(440, 500);
  silence(200);
  Serial.println("880Hz");
  play_tone(880, 500);
  silence(200);
  Serial.println("1320Hz");
  play_tone(1320, 500);
  silence(1000);
}
