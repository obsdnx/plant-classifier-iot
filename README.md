# plant-health-classifier

Raspberry Pi captures a leaf photo → sends it to a computer over Wi-Fi → CNN classifies it → Ollama LLM explains the diagnosis → verdict returned to the Pi.

## The hat

**Concept sketches** — early design, showing where the ultrasonic sensor, ESP32 and waterproof shell sit.

![Hand-drawn sketches of the hat from two angles, annotated with electronics in the upper band, an ultrasonic sensor and ESP32 under the brim, and waterproof material](docs/images/hat-concept-sketches.png)

**Components** — exploded view of the build.

![Exploded view of the hat labelling the outer fabric shell, ESP32 Freenove board, battery pack, speaker, ultrasonic sensor, ESP32-CAM, database and interfacing](docs/images/hat-exploded-view.png)

**Prototype** — the finished hat.

![The completed cream and blue floral hat being worn outdoors](docs/images/hat-prototype-worn.png)

## Folder structure

```
computer/
├── server.py        FastAPI server — receives photo, runs CNN, calls LLM
├── classifier.py    Loads pumpkin.tflite and runs inference
├── explainer.py     Calls Ollama for a plain-language explanation
├── labels.txt       One label per line, in the same order as the model output
├── pumpkin.tflite   ← YOU MUST ADD THIS (not included in repo)
└── requirements.txt

pi/
├── client.py        Takes photo, sends to server, prints verdict
├── config.py        Set COMPUTER_IP here before running
├── photos/          Saved photos (for debugging)
└── requirements.txt
```

## Setup

### Computer

```bash
cd computer
pip install -r requirements.txt
# Copy your pumpkin.tflite into this folder
# Install and start Ollama: https://ollama.com
ollama pull llama3.2
python server.py
```

### Raspberry Pi

1. Edit `pi/config.py` — set `COMPUTER_IP` to your computer's local IP address.
2. Copy the `pi/` folder to the Pi.
3. On the Pi:

```bash
pip install -r requirements.txt
python client.py
```

Press the button on GPIO 17 to take a photo and get a verdict.

## JSON contract

```json
{
  "label": "Downy mildew",
  "confidence": 0.87,
  "status": "ok",
  "explanation": "Downy mildew is a fungus-like disease..."
}
```

`status` is `"ok"`, `"unsure"` (confidence < 60 %), or `"error"`.
