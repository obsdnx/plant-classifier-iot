// HC-SR04 ultrasonic distance sensor on ESP32-S3
// Trig -> GPIO 1, Echo -> GPIO 2 (through voltage divider)

const int TRIG = 1;
const int ECHO = 2;

void setup() {
  Serial.begin(115200);
  pinMode(TRIG, OUTPUT);
  pinMode(ECHO, INPUT);
  digitalWrite(TRIG, LOW);
}

void loop() {
  digitalWrite(TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG, LOW);

  long us = pulseIn(ECHO, HIGH, 30000);  // 30 ms timeout = about 5 m
  if (us == 0) {
    Serial.println("No echo (nothing in range, or check wiring)");
  } else {
    Serial.printf("Distance: %.1f cm\n", us / 58.0);
  }
  delay(200);
}
