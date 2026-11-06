import asyncio
import json

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import uvicorn

import hat
import webcam

from classifier import classify
from explainer import explain

CONFIDENCE_THRESHOLD_REAL = 0.60
CONFIDENCE_THRESHOLD_DEMO = 0.00

app = FastAPI(title="Plant Health Classifier")

_static = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static)), name="static")
app.mount("/records", StaticFiles(directory=str(hat.RECORDS_DIR)), name="records")


@app.on_event("startup")
async def startup():
    hat.attach_loop(asyncio.get_running_loop())
    hat.start_sensor_thread()
    hat.info(f"Server started. Claude {'connected' if hat.claude_ready() else 'NOT connected (no ANTHROPIC_API_KEY)'}")
    if webcam.start():
        hat.info("Laptop webcam started (server-side capture ready)")
    else:
        hat.info("No laptop webcam found — using browser camera only", "warn")


@app.get("/")
def dashboard():
    return FileResponse(str(_static / "hat.html"))


@app.get("/upload")
def upload_page():
    return FileResponse(str(_static / "index.html"))


@app.get("/api/status")
def status():
    import classifier_plantvillage as _pv
    return {**hat.state, "claude_ready": hat.claude_ready(), "claude_model": hat.CLAUDE_MODEL,
            "hatcam_stream": hat.hatcam_stream_url(),
            "classifier_demo": __import__("classifier").DEMO_MODE,
            "pv_classifier_demo": _pv.DEMO_MODE,
            "trigger_cm": hat.TRIGGER_CM, "cooldown_s": hat.COOLDOWN_S,
            "speaker_ready": hat.speaker_ready()}


@app.post("/api/monitoring")
def set_monitoring(body: dict):
    enabled = bool(body.get("enabled", True))
    hat.state["monitoring_enabled"] = enabled
    hat.info(f"Monitoring {'enabled' if enabled else 'disabled'} via dashboard")
    hat.publish("monitoring", enabled=enabled)
    return {"monitoring_enabled": enabled}


@app.get("/api/volume")
def get_volume():
    return {"volume": hat.state.get("volume", 0.8)}


@app.post("/api/volume")
def set_volume(body: dict):
    v = max(0.0, min(1.0, float(body.get("volume", 0.8))))
    hat.state["volume"] = v
    return {"volume": v}


@app.get("/api/history")
def get_history():
    return hat.history()


@app.get("/api/log")
def get_log():
    return list(hat.log)


@app.post("/api/trigger")
def manual_trigger():
    hat.state["last_trigger"] = 0
    return {"triggered": hat.trigger("dashboard button")}


@app.post("/api/analyze")
def analyze(image: UploadFile = File(...), source: str = Form("manual")):
    if hat.state["busy"]:
        raise HTTPException(status_code=409, detail="Still processing the previous picture")
    return hat.run_pipeline(image.file.read(), source)


@app.post("/api/tts")
def tts(body: dict):
    """Turn text into 8 kHz 8-bit raw audio the ESP32 speaker can download and play."""
    import socket, subprocess, uuid, wave
    text = str(body.get("text", ""))[:400]
    tts_dir = hat.RECORDS_DIR / "tts"
    tts_dir.mkdir(exist_ok=True)
    name = uuid.uuid4().hex[:8]
    wav = tts_dir / f"{name}.wav"
    subprocess.run(["say", "-r", "165", "-o", str(wav), "--file-format=WAVE", "--data-format=UI8@8000", text], check=True)
    with wave.open(str(wav)) as w:
        frames = w.readframes(w.getnframes())
    wav.unlink()
    # No loudness boost: with the speaker wired straight to the pin, louder audio browns out the ESP32.
    (tts_dir / f"{name}.raw").write_bytes(frames[: 8000 * 12])  # max 12 s fits in ESP32 memory
    for old in sorted(tts_dir.glob("*.raw"))[:-20]:
        old.unlink()
    s_ = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s_.connect(("8.8.8.8", 80))
    lan_ip = s_.getsockname()[0]
    s_.close()
    return {"url": f"http://{lan_ip}:8000/records/tts/{name}.raw", "seconds": round(min(len(frames), 96000) / 8000, 1)}


@app.post("/api/speak")
def speak(body: dict):
    """Speak text through WiFi or USB serial speaker."""
    text = str(body.get("text", ""))[:400]
    if not text:
        raise HTTPException(status_code=400, detail="text required")
    ok = hat.speak(text)
    if not ok:
        raise HTTPException(status_code=500, detail="Speaker not reachable (WiFi or serial)")
    return {"spoken": text}


@app.get("/api/events")
async def events():
    q = hat.subscribe()

    async def stream():
        try:
            yield f"data: {json.dumps({'kind': 'hello', 'status': status()})}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            hat.unsubscribe(q)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/webcam/stream")
def webcam_stream():
    if not webcam.is_ready():
        raise HTTPException(status_code=503, detail="Webcam not available")
    return StreamingResponse(
        webcam.mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/webcam/capture")
def webcam_capture():
    frame = webcam.capture()
    if not frame:
        raise HTTPException(status_code=503, detail="No webcam frame")
    return Response(content=frame, media_type="image/jpeg")


@app.get("/api/webcam/status")
def webcam_status():
    return {"ready": webcam.is_ready()}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/classify")
async def classify_leaf(image: UploadFile = File(...)):
    if not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image.")

    image_bytes = await image.read()

    try:
        result = classify(image_bytes)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": str(e)},
        )

    label = result["label"]
    confidence = result["confidence"]
    threshold = CONFIDENCE_THRESHOLD_DEMO if result.get("demo") else CONFIDENCE_THRESHOLD_REAL

    if confidence < threshold:
        return {
            "label": label,
            "confidence": round(confidence, 4),
            "status": "unsure",
            "explanation": (
                f"Confidence too low ({confidence*100:.0f}%). "
                "Please retake the photo in better light, filling the frame with the leaf."
            ),
        }

    explanation = explain(label)

    return {
        "label": label,
        "confidence": round(confidence, 4),
        "status": "ok",
        "explanation": explanation,
        "demo": result.get("demo", False),
    }


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
