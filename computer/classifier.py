import torch
import numpy as np
from PIL import Image
from pathlib import Path
from io import BytesIO
import random
from transformers import AutoImageProcessor, AutoModelForImageClassification

MODEL_DIR = Path(__file__).parent / "model"
LABELS_PATH = Path(__file__).parent / "labels.txt"

DEMO_MODE = not MODEL_DIR.exists()

_model = None
_extractor = None
_labels = None


def _load():
    global _model, _extractor, _labels
    print("Loading model (first request)...")
    _extractor = AutoImageProcessor.from_pretrained(str(MODEL_DIR))
    _model = AutoModelForImageClassification.from_pretrained(str(MODEL_DIR))
    _model.eval()
    _labels = LABELS_PATH.read_text().strip().splitlines()
    print(f"Model ready. {len(_labels)} classes.")


def classify(image_bytes: bytes) -> dict:
    global _model, _extractor, _labels

    if DEMO_MODE:
        labels = LABELS_PATH.read_text().strip().splitlines()
        scores = [random.random() for _ in labels]
        total = sum(scores)
        scores = [s / total for s in scores]
        i = scores.index(max(scores))
        return {
            "label": labels[i],
            "confidence": round(scores[i], 4),
            "all_scores": {labels[j]: round(scores[j], 4) for j in range(len(labels))},
            "demo": True,
        }

    if _model is None:
        _load()

    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    inputs = _extractor(images=img, return_tensors="pt")

    with torch.no_grad():
        logits = _model(**inputs).logits

    probs = torch.softmax(logits, dim=-1)[0].tolist()
    i = int(torch.argmax(logits, dim=-1).item())

    return {
        "label": _labels[i],
        "confidence": round(probs[i], 4),
        "all_scores": {_labels[j]: round(probs[j], 4) for j in range(len(_labels))},
        "demo": False,
    }
