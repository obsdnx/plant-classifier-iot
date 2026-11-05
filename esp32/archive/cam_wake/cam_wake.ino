#include <Wire.h>
#include "soc/gpio_reg.h"

const int XCLK = 15;
int watch[] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 18, 21, 38, 39, 40, 41, 42, 45, 46, 47, 48};
int ctrl[] = {14, 1, 2, 3, 21, 38, 39, 40, 41, 42, 45, 46, 47, 48};
uint8_t addrs[] = {0x21, 0x30, 0x3C, 0x68, 0x6E};

int level(int p) {
  pinMode(p, INPUT_PULLUP);   delayMicroseconds(300); int u = digitalRead(p);
  pinMode(p, INPUT_PULLDOWN); delayMicroseconds(300); int d = digitalRead(p);
  pinMode(p, INPUT);
  return (u && d) ? 'H' : (!u && !d) ? 'L' : '-';
}

String activity(int skip) {
  for (int p : watch) if (p != skip) pinMode(p, INPUT);
  uint32_t cnt[49] = {0};
  uint64_t prev = (uint64_t)REG_READ(GPIO_IN_REG) | ((uint64_t)REG_READ(GPIO_IN1_REG) << 32);
  uint32_t end = millis() + 300;
  while (millis() < end) {
    uint64_t cur = (uint64_t)REG_READ(GPIO_IN_REG) | ((uint64_t)REG_READ(GPIO_IN1_REG) << 32);
    uint64_t diff = cur ^ prev;
    if (diff) for (int p : watch) if (p != skip && (diff >> p & 1)) cnt[p]++;
    prev = cur;
  }
  String s;
  for (int p : watch) if (cnt[p] > 5) s += String(p) + ":" + cnt[p] + " ";
  return s.length() ? s : "none";
}

String scan(int sda, int scl) {
  if (level(sda) == 'L' || level(scl) == 'L') return "bus-low";
  Wire.begin(sda, scl, 100000);
  Wire.setTimeOut(20);
  String s;
  for (uint8_t a : addrs) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) s += "0x" + String(a, HEX) + " ";
  }
  Wire.end();
  return s.length() ? s : "none";
}

void report(const char* tag, int skip) {
  Serial.printf("%-12s pin5=%c pin4=%c pin14=%c | i2c(4,5)=%s | activity=%s\n",
    tag, level(5), level(4), skip == 14 ? '*' : level(14), scan(4, 5).c_str(), activity(skip).c_str());
}

void setup() {
  Serial.begin(115200);
  delay(4000);
  esp_log_level_set("*", ESP_LOG_NONE);
  Serial.println("WAKE START");
  ledcAttach(XCLK, 20000000, 1);
  ledcWrite(XCLK, 1);
  delay(200);
  report("baseline", -1);
  for (int c : ctrl) {
    for (int v = 0; v < 2; v++) {
      pinMode(c, OUTPUT);
      digitalWrite(c, v);
      delay(100);
      char tag[16];
      snprintf(tag, sizeof(tag), "G%d=%s", c, v ? "HIGH" : "LOW");
      report(tag, c);
      pinMode(c, INPUT);
    }
  }
  Serial.println("WAKE DONE");
}

void loop() { delay(1000); }
