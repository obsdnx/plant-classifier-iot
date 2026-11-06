#include <Wire.h>
#include "soc/gpio_reg.h"

const int XCLK = 15;
int pins[] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 18, 21, 38, 39, 40, 41, 42, 45, 46, 47, 48};
const int N = sizeof(pins) / sizeof(pins[0]);
uint8_t addrs[] = {0x21, 0x30, 0x3C, 0x68, 0x6E};

uint64_t readAll() {
  return (uint64_t)REG_READ(GPIO_IN_REG) | ((uint64_t)REG_READ(GPIO_IN1_REG) << 32);
}

void levels(const char* tag) {
  Serial.printf("LEVELS (%s): ", tag);
  for (int p : pins) {
    pinMode(p, INPUT_PULLUP);   delayMicroseconds(500); int u = digitalRead(p);
    pinMode(p, INPUT_PULLDOWN); delayMicroseconds(500); int d = digitalRead(p);
    pinMode(p, INPUT);
    Serial.printf("%d=%s ", p, (u && d) ? "H" : (!u && !d) ? "L" : "-");
  }
  Serial.println();
}

void activity(const char* tag) {
  for (int p : pins) pinMode(p, INPUT);
  uint32_t cnt[49] = {0};
  uint64_t prev = readAll();
  uint32_t end = millis() + 1000;
  while (millis() < end) {
    uint64_t cur = readAll(), diff = cur ^ prev;
    if (diff) for (int p : pins) if (diff >> p & 1) cnt[p]++;
    prev = cur;
  }
  Serial.printf("ACTIVITY (%s): ", tag);
  bool any = false;
  for (int p : pins) if (cnt[p]) { Serial.printf("%d:%u ", p, cnt[p]); any = true; }
  Serial.println(any ? "" : "none");
}

void scanPair(int sda, int scl, bool allAddrs) {
  Wire.begin(sda, scl, 100000);
  Wire.setTimeOut(20);
  for (int a = 1; a < 127; a++) {
    if (!allAddrs) { bool want = false; for (uint8_t x : addrs) want |= (x == a); if (!want) continue; }
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) Serial.printf("I2C_FOUND sda=%d scl=%d addr=0x%02X\n", sda, scl, a);
  }
  Wire.end();
}

void setup() {
  Serial.begin(115200);
  delay(4000);
  esp_log_level_set("*", ESP_LOG_NONE);
  Serial.println("DIAG START");
  levels("no clock");
  activity("no clock");

  ledcAttach(XCLK, 20000000, 1);
  ledcWrite(XCLK, 1);
  delay(300);
  levels("clock on 15");
  activity("clock on 15");

  Serial.println("SCAN sda=4 scl=5 all addresses");
  scanPair(4, 5, true);
  Serial.println("SCAN all pin pairs");
  for (int i = 0; i < N; i++)
    for (int j = 0; j < N; j++)
      if (i != j) scanPair(pins[i], pins[j], false);
  Serial.println("DIAG DONE");
}

void loop() {
  delay(1000);
}
