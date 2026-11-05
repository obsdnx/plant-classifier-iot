"""Plant-health hat backend: ultrasonic trigger -> photo -> CNN classifier -> Claude -> spoken answer -> saved record.
Every step is published as an event so the dashboard can show it live."""
import asyncio, base64, glob, json, os, re, socket, struct, subprocess
import tempfile, threading, time, uuid, wave
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
HATSENSOR_URL = os.environ.get("HATSENSOR_URL", "http://hatsensor.local")
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
    "hatsensor_online": False,
    "monitoring_enabled": True,
    "trigger_count": 0,
    "run_count": 0,
    "speaker_port": None,
    "volume": 0.8,
}

# ---------- serial speaker ----------
_SPEAK_MAGIC = b"\xaa\xbb"
_SPEAK_BAUD  = 115200
_SPEAK_RATE  = 8000


def _find_speaker_port() -> str | None:
    candidates = glob.glob("/dev/cu.usbserial-*")
    return candidates[0] if candidates else None


def _generate_audio(text: str) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name
    subprocess.run(
        ["say", "-v", "Samantha", "-r", "140", "-o", wav_path,
         "--file-format=WAVE", "--data-format=UI8@8000", text],
        check=True
    )
    with wave.open(wav_path) as w:
        raw = w.readframes(w.getnframes())
    os.unlink(wav_path)
    return raw[: _SPEAK_RATE * 12]


def _apply_volume(audio: bytes) -> bytes:
    import numpy as np
    v = float(state.get("volume", 0.8))
    arr = np.frombuffer(audio, dtype=np.uint8).astype(np.float32)
    arr = (arr - 128.0) * v + 128.0
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return arr.tobytes()


def speak_serial(text: str, run_id: str = "") -> bool:
    """Generate audio and send to ESP32 speaker over USB serial. Returns True on success."""
    port = _find_speaker_port()
    if not port:
        info("Serial speaker: no usbserial port found", "warn")
        return False
    state["speaker_port"] = port
    try:
        audio = _apply_volume(_generate_audio(text))
        info(f"[{run_id}] Serial speaker: {len(audio)} bytes → {port}")
        ser = serial.Serial(port, _SPEAK_BAUD, timeout=5)
        time.sleep(0.3)
        ser.reset_input_buffer()
        ser.write(_SPEAK_MAGIC + struct.pack("<I", len(audio)))
        ser.flush()
        # wait for ACK
        deadline = time.time() + 5
        while time.time() < deadline:
            line = ser.readline().decode(errors="ignore").strip()
            if line.startswith("RECV"):
                break
        else:
            info(f"[{run_id}] Serial speaker: no ACK from ESP32", "warn")
            ser.close()
            return False
        ser.write(audio)
        ser.flush()
        # wait for DONE
        deadline = time.time() + 20
        while time.time() < deadline:
            line = ser.readline().decode(errors="ignore").strip()
            if line == "DONE":
                info(f"[{run_id}] Serial speaker: playback done")
                ser.close()
                return True
        ser.close()
        return False
    except Exception as e:
        info(f"[{run_id}] Serial speaker failed: {e}", "error")
        state["speaker_port"] = None
        return False


def speak_serial_async(text: str, run_id: str = "", on_done=None):
    """Fire-and-forget: speak in a background thread, call on_done(success) when finished."""
    def _run():
        ok = speak_serial(text, run_id)
        if on_done:
            on_done(ok)
    threading.Thread(target=_run, daemon=True).start()


def speaker_ready() -> bool:
    return state.get("hatsensor_online", False) or bool(_find_speaker_port())
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
        try:
            import webcam as _webcam
            if _webcam.is_ready():
                info(f"TRIGGER ({source}) - capturing from server-side laptop webcam")
                publish("trigger", source=source, server_capture=True)
                threading.Thread(target=_laptop_capture_and_run, args=(source,), daemon=True).start()
                return True
        except ImportError:
            pass
        info(f"TRIGGER ({source}) - asking the dashboard to take a webcam picture")
        publish("trigger", source=source, server_capture=False)
    return True


def _laptop_capture_and_run(source):
    try:
        import webcam as _webcam
        img = _webcam.capture()
        if not img:
            info("Laptop webcam capture returned nothing", "error")
            publish("trigger", source=source, server_capture=False)
            return
        info(f"Captured from laptop webcam ({len(img) // 1024} KB)")
    except Exception as e:
        info(f"Laptop webcam capture failed: {e}", "error")
        publish("trigger", source=source, server_capture=False)
        return
    run_pipeline(img, source)


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
    "and two CNN classifiers give a first guess. "
    "Classifier 1 (Pumpkin CNN) is trained on pumpkin leaf diseases: Bacterial Leaf Spot, Downy Mildew, Healthy Leaf, "
    "Mosaic Disease, Powdery Mildew. "
    "Classifier 2 (PlantVillage CNN) is trained ONLY on tomatoes, peppers, and potatoes — it has never seen "
    "pumpkin, squash, or cucumber leaves. If the plant in the photo is not a tomato, pepper, or potato, "
    "the PlantVillage CNN prediction is unreliable and should be ignored. "
    "Trust the Pumpkin CNN for pumpkin/squash/cucumber leaves; trust PlantVillage CNN only for its 3 plant types. "
    "You look at the photo yourself and give the final answer. "
    "Fields: plant_visible = is a plant or leaf actually in the photo; healthy = does it look healthy; "
    "diagnosis = one or two sentences on what you see and why, noting if a classifier prediction seems wrong due to plant type mismatch; "
    "agrees_with_classifier = whether the most relevant CNN guess matches what you see; "
    "spoken = what the hat says out loud: at most two short, friendly sentences, plain words, "
    "no symbols or percentages. If no plant is visible, say so in spoken and ask the wearer to hold a leaf closer."
)

_client = None


def claude_ready():
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _detect_media_type(image_bytes: bytes) -> str:
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image_bytes[:3] == b"GIF":
        return "image/gif"
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def ask_claude(image_bytes, cnn, pv=None):
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    media_type = _detect_media_type(image_bytes)
    cnn_text = f"Pumpkin-disease CNN guess: {cnn['label']} ({cnn['confidence'] * 100:.0f}% confidence)."
    if pv and pv.get("label") and pv.get("label") != "unknown":
        cnn_text += (f" PlantVillage CNN guess: {pv['label']} ({pv['confidence'] * 100:.0f}% confidence,"
                     f" healthy={pv.get('healthy')}).")
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
                {"type": "image", "source": {"type": "base64", "media_type": media_type,
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


TTS_DIR = RECORDS_DIR / "tts"
TTS_DIR.mkdir(exist_ok=True)


def _lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip


def speak_wifi(text: str) -> bool:
    """Generate TTS audio, serve it, and tell hatsensor.local to play it."""
    try:
        audio = _apply_volume(_generate_audio(text))
        name = uuid.uuid4().hex[:8]
        raw_path = TTS_DIR / f"{name}.raw"
        raw_path.write_bytes(audio)
        for old in sorted(TTS_DIR.glob("*.raw"))[:-20]:
            old.unlink()
        url = f"http://{_lan_ip()}:8000/records/tts/{name}.raw"
        resp = requests.get(f"{HATSENSOR_URL}/say?url={url}", timeout=(3, 30))
        state["hatsensor_online"] = resp.status_code == 200
        return resp.status_code == 200
    except Exception as e:
        info(f"WiFi speak failed: {e}", "error")
        state["hatsensor_online"] = False
        return False


def speak(text: str) -> bool:
    """Try WiFi speaker first, fall back to serial."""
    if speak_wifi(text):
        return True
    return speak_serial(text)


# ---------- pipeline ----------
def step(run_id, name, status, **data):
    publish("step", run=run_id, step=name, status=status, **data)


def run_pipeline(image_bytes, source="manual"):
    run_id = time.strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:4]
    state["busy"] = True
    state["run_count"] += 1
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
            info(f"[{run_id}] pumpkin classifier: {cnn['label']} {cnn['confidence'] * 100:.0f}% in {ms} ms")
        except Exception as e:
            cnn = {"label": "unknown", "confidence": 0.0}
            record["classifier"] = {"error": str(e)}
            step(run_id, "classifier", "error", detail={"error": str(e)})
            info(f"[{run_id}] pumpkin classifier failed: {e}", "error")

        step(run_id, "pv_classifier", "running")
        t0 = time.time()
        try:
            pv = classify_plantvillage(image_bytes)
            ms = int((time.time() - t0) * 1000)
            record["pv_classifier"] = pv
            step(run_id, "pv_classifier", "done", ms=ms, detail=pv)
            info(f"[{run_id}] plantvillage classifier: {pv['label']} {pv['confidence'] * 100:.0f}% in {ms} ms")
        except Exception as e:
            pv = {"label": "unknown", "confidence": 0.0, "healthy": None}
            record["pv_classifier"] = {"error": str(e)}
            step(run_id, "pv_classifier", "error", detail={"error": str(e)})
            info(f"[{run_id}] plantvillage classifier failed: {e}", "error")

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
                answer, meta = ask_claude(image_bytes, cnn, pv)
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

        spoken_text = answer["spoken"]
        step(run_id, "speak", "running", detail={"text": spoken_text})
        def _do_speak(_rid=run_id, _t=spoken_text):
            ok = speak(_t)
            step(_rid, "speak", "done" if ok else "error",
                 detail={"text": _t, "ok": ok})
        threading.Thread(target=_do_speak, daemon=True).start()

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
