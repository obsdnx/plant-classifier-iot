// ESP32 I2S sound test — Arduino core 3.x API
// MAX98357A: BCLK=32  DIN=33  LRC=35

#include "ESP_I2S.h"
#include <math.h>

#define I2S_BCLK   32
#define I2S_DOUT   33
#define I2S_LRC    35

#define SAMPLE_RATE 16000
#define AMPLITUDE   28000

I2SClass i2s;

void play_tone(int freq, int ms) {
  int samples = SAMPLE_RATE * ms / 1000;
  for (int i = 0; i < samples; i++) {
    int16_t s = (int16_t)(AMPLITUDE * sin(2.0 * M_PI * freq * i / SAMPLE_RATE));
    i2s.write(s);
  }
}

void setup() {
  Serial.begin(115200);
  i2s.setPins(I2S_BCLK, I2S_LRC, I2S_DOUT);
  i2s.begin(I2S_MODE_STD, SAMPLE_RATE, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO);
  Serial.println("I2S ready");
}

void loop() {
  Serial.println("beep 440Hz");
  play_tone(440, 500);
  delay(200);
  Serial.println("beep 880Hz");
  play_tone(880, 500);
  delay(200);
  Serial.println("beep 1320Hz");
  play_tone(1320, 500);
  delay(800);
}
