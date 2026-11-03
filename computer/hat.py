"""Plant-health hat backend: ultrasonic trigger -> photo -> CNN classifier -> Claude -> spoken answer -> saved record.
Every step is published as an event so the dashboard can show it live."""
import asyncio, base64, glob, json, os, re, socket, threading, time, uuid
from urllib.parse import urlparse
from collections import deque
from pathlib import Path

import anthropic
import requests
import serial

from classifier import classify
from classifier_plantvillage import classify_plantvillage

ENV_FILE = Path(__file__).parent / ".env"
if ENV_FILE.exists():
    for _line in ENV_FILE.read_text().splitlines():
        _k, _, _v = _line.partition("=")
        if _k.strip() and _v.strip() and not _line.lstrip().startswith("#"):
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

TRIGGER_CM = 5.0
COOLDOWN_S = 8.0
CLAUDE_MODEL = "claude-opus-5-5"
HATCAM_URL = os.environ.get("HATCAM_URL", "http://hatcam.local")
RECORDS_DIR = Path(__file__).parent / "records"
RECORDS_DIR.mkdir(exist_ok=True)
HISTORY_FILE = RECORDS_DIR / "history.jsonl"

state = {
    "distance": None,
    "sensor_connected": False,
    "sensor_port": None,
    "last_trigger": 0.0,
    "busy": False,
    "hatcam_online": False,
    "hatcam_ip": None,
    "monitoring_enabled": True,
    "trigger_count": 0,
    "run_count": 0,
}
log = deque(maxlen=300)

# ---------- event bus (thread-safe -> asyncio SSE clients) ----------
_loop = None
_clients = set()


def attach_loop(loop):
    global _loop
    _loop = loop


def subscribe():
    q = asyncio.Queue(maxsize=500)
    _clients.add(q)
    return q


def unsubscribe(q):
    _clients.discard(q)


def publish(kind, **data):
    event = {"kind": kind, "t": time.time(), **data}
    if kind == "log":
        log.append(event)
    if _loop is None:
        return
    for q in list(_clients):
        _loop.call_soon_threadsafe(_put_nowait, q, event)


def _put_nowait(q, event):
    try:
        q.put_nowait(event)
    except asyncio.QueueFull:
        pass


def info(msg, level="info"):
    print(f"[{level}] {msg}")
    publish("log", level=level, msg=msg)


# ---------- ultrasonic sensor ----------
def trigger(source):
    now = time.time()
    if not state["monitoring_enabled"]:
        info(f"Trigger from {source} ignored: monitoring is disabled", "warn")
        return False
    if state["busy"]:
        info(f"Trigger from {source} ignored: still processing the last picture", "warn")
        return False
    if now - state["last_trigger"] < COOLDOWN_S:
        return False
    state["last_trigger"] = now
    state["trigger_count"] += 1
    if state["hatcam_online"]:
        info(f"TRIGGER ({source}) - getting a photo from the hat camera")
        publish("trigger", source=source, server_capture=True)
        threading.Thread(target=_hatcam_capture_and_run, args=(source,), daemon=True).start()
    else:
        info(f"TRIGGER ({source}) - asking the dashboard to take a webcam picture")
        publish("trigger", source=source, server_capture=False)
    return True


def _sensor_loop():
    last_pub = 0.0
    while True:
        ports = glob.glob("/dev/cu.usbmodem*")  # ESP32-S3 sensor board; usbserial ports are left free for flashing the ESP32-CAM
        if not ports:
            if state["sensor_connected"]:
                info("Ultrasonic sensor disconnected", "warn")
            state.update(sensor_connected=False, sensor_port=None, distance=None)
            publish("sensor", connected=False, distance=None)
            time.sleep(1)
            continue
        try:
            with serial.Serial(ports[0], 115200, timeout=2) as ser:
                state.update(sensor_connected=True, sensor_port=ports[0])
                info(f"Ultrasonic sensor connected on {ports[0]}")
                while True:
                    line = ser.readline().decode(errors="ignore")
                    m = re.search(r"Distance:\s*([\d.]+)", line)
                    if m:
                        state["distance"] = float(m.group(1))
                    elif "No echo" in line:
                        state["distance"] = None
                    else:
                        continue
                    if state["hatcam_online"]:
                        continue
                    now = time.time()
                    if now - last_pub > 0.15:
                        publish("sensor", connected=True, distance=state["distance"])
                        last_pub = now
                    d = state["distance"]
                    if d is not None and 2.0 <= d < TRIGGER_CM:
                        trigger(f"hand wave {d:.1f} cm")
        except serial.SerialException as e:
            state.update(sensor_connected=False, distance=None)
            info(f"Sensor serial error: {e}", "error")
            publish("sensor", connected=False, distance=None)
            time.sleep(2)


def _hatcam_base():
    """Resolve hatcam.local once (mDNS lookups are slow) and reuse the IP."""
    if not state["hatcam_ip"]:
        state["hatcam_ip"] = socket.gethostbyname(urlparse(HATCAM_URL).hostname)
    return f"http://{state['hatcam_ip']}"


def _set_hatcam(online):
    if online == state["hatcam_online"]:
        return
    state["hatcam_online"] = online
    if online:
        info(f"Hat camera connected over WiFi at {state['hatcam_ip']}")
    else:
        info("Hat camera (WiFi) not reachable", "warn")
        state["hatcam_ip"] = None
    publish("hatcam", online=online, stream=hatcam_stream_url())


def hatcam_stream_url():
    return f"http://{state['hatcam_ip']}:81/stream" if state["hatcam_online"] else None


def _hatcam_loop():
    last_pub = 0.0
    while True:
        if state["busy"]:
            time.sleep(0.2)
            continue
        try:
            d = requests.get(_hatcam_base() + "/distance", timeout=1.5).json()["cm"]
        except Exception:
            _set_hatcam(False)
            state["hatcam_ip"] = None
            time.sleep(2)
            continue
        _set_hatcam(True)
        state["distance"] = d
        now = time.time()
        if now - last_pub > 0.15:
            publish("sensor", connected=True, distance=d, source="hat (WiFi)")
            last_pub = now
        if d is not None and d < TRIGGER_CM:
            trigger(f"hand wave {d:.1f} cm")
        time.sleep(0.12)


def _hatcam_capture_and_run(source):
    try:
        t0 = time.time()
        img = requests.get(_hatcam_base() + "/capture", timeout=10).content
        info(f"Got photo from hat camera ({len(img) // 1024} KB) in {int((time.time() - t0) * 1000)} ms")
    except Exception as e:
        info(f"Could not get a photo from the hat camera: {e}", "error")
        return
    run_pipeline(img, source)


def start_sensor_thread():
    threading.Thread(target=_sensor_loop, daemon=True).start()
    threading.Thread(target=_hatcam_loop, daemon=True).start()


# ---------- Claude ----------
CLAUDE_SCHEMA = {
    "type": "object",
    "properties": {
        "plant_visible": {"type": "boolean"},
        "healthy": {"type": "boolean"},
        "diagnosis": {"type": "string"},
        "agrees_with_classifier": {"type": "boolean"},
        "spoken": {"type": "string"},
    },
    "required": ["plant_visible", "healthy", "diagnosis", "agrees_with_classifier", "spoken"],
    "additionalProperties": False,
}

SYSTEM = (
    "You are the voice of a wearable plant-health hat. The wearer waves a hand, the hat photographs a plant leaf, "
    "and a small CNN classifier trained on pumpkin leaf diseases (Bacterial Leaf Spot, Downy Mildew, Healthy Leaf, "
    "Mosaic Disease, Powdery Mildew) gives a first guess. You look at the photo yourself and give the final answer. "
    "Fields: plant_visible = is a plant or leaf actually in the photo; healthy = does it look healthy; "
    "diagnosis = one or two sentences on what you see and why; agrees_with_classifier = whether the CNN guess "
    "matches what you see; spoken = what the hat says out loud: at most two short, friendly sentences, plain words, "
    "no symbols or percentages. If no plant is visible, say so in spoken and ask the wearer to hold a leaf closer."
)

_client = None


def claude_ready():
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def ask_claude(image_bytes, cnn):
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    cnn_text = f"CNN classifier guess: {cnn['label']} ({cnn['confidence'] * 100:.0f}% confidence)."
    response = _client.beta.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": CLAUDE_SCHEMA}},
        system=SYSTEM,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": base64.standard_b64encode(image_bytes).decode()}},
                {"type": "text", "text": cnn_text},
            ],
        }],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined to answer this image")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text), {"model": response.model, "input_tokens": response.usage.input_tokens,
                              "output_tokens": response.usage.output_tokens, "request_id": response._request_id}


# ---------- pipeline ----------
def step(run_id, name, status, **data):
    publish("step", run=run_id, step=name, status=status, **data)


def run_pipeline(image_bytes, source="manual"):
    run_id = time.strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:4]
    state["busy"] = True
    record = {"id": run_id, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "source": source,
              "distance_cm": state["distance"], "photo": f"/records/{run_id}.jpg"}
    publish("run_start", run=run_id, source=source)
    try:
        t0 = time.time()
        (RECORDS_DIR / f"{run_id}.jpg").write_bytes(image_bytes)
        step(run_id, "capture", "done", ms=int((time.time() - t0) * 1000),
             detail={"bytes": len(image_bytes), "photo": record["photo"]})
        info(f"[{run_id}] photo saved ({len(image_bytes) // 1024} KB)")

        step(run_id, "classifier", "running")
        t0 = time.time()
        try:
            cnn = classify(image_bytes)
            ms = int((time.time() - t0) * 1000)
            record["classifier"] = cnn
            step(run_id, "classifier", "done", ms=ms, detail=cnn)
            info(f"[{run_id}] classifier: {cnn['label']} {cnn['confidence'] * 100:.0f}% in {ms} ms")
        except Exception as e:
            cnn = {"label": "unknown", "confidence": 0.0}
            record["classifier"] = {"error": str(e)}
            step(run_id, "classifier", "error", detail={"error": str(e)})
            info(f"[{run_id}] classifier failed: {e}", "error")

        step(run_id, "claude", "running")
        t0 = time.time()
        if not claude_ready():
            answer = {"plant_visible": None, "healthy": cnn["label"] == "Healthy Leaf",
                      "diagnosis": "Claude is not connected (no ANTHROPIC_API_KEY). Showing the classifier result only.",
                      "agrees_with_classifier": None,
                      "spoken": f"The classifier thinks this is {cnn['label'].replace('_', ' ')}."}
            record["claude"] = {"skipped": "no API key", **answer}
            step(run_id, "claude", "skipped", detail=record["claude"])
            info(f"[{run_id}] Claude skipped: set ANTHROPIC_API_KEY to enable it", "warn")
        else:
            try:
                answer, meta = ask_claude(image_bytes, cnn)
                ms = int((time.time() - t0) * 1000)
                record["claude"] = {**answer, **meta}
                step(run_id, "claude", "done", ms=ms, detail=record["claude"])
                info(f"[{run_id}] Claude: {'healthy' if answer['healthy'] else 'NOT healthy'} in {ms} ms")
            except Exception as e:
                answer = {"healthy": None, "spoken": "Sorry, I could not reach Claude.", "diagnosis": str(e)}
                record["claude"] = {"error": str(e)}
                step(run_id, "claude", "error", detail={"error": str(e)})
                info(f"[{run_id}] Claude failed: {e}", "error")

        record["spoken"] = answer["spoken"]
        record["healthy"] = answer.get("healthy")
        step(run_id, "speak", "send", detail={"text": answer["spoken"]})

        with HISTORY_FILE.open("a") as f:
            f.write(json.dumps(record) + "\n")
        step(run_id, "saved", "done", detail={"file": str(HISTORY_FILE.name), "id": run_id})
        publish("run_done", run=run_id, record=record)
        return record
    finally:
        state["busy"] = False


def history(limit=50):
    if not HISTORY_FILE.exists():
        return []
    lines = HISTORY_FILE.read_text().strip().splitlines()
    return [json.loads(l) for l in reversed(lines[-limit:])]
