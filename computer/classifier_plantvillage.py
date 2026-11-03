"""PlantVillage CNN classifier — Keras model trained on 15 disease classes.

Model source: https://github.com/biswadeep-roy/Plant-Health-Classifier
Input: 256×256 RGB. Architecture: 6×(Conv2D + MaxPool) → Dense(64) → Dense(15, softmax).
"""
import numpy as np
from PIL import Image
from pathlib import Path
from io import BytesIO
import random

MODEL_PATH = Path(__file__).parent / "model_plantvillage.h5"

CLASS_NAMES = [
    "Pepper__bell___Bacterial_spot",
    "Pepper__bell___healthy",
    "Potato___Early_blight",
    "Potato___Late_blight",
    "Potato___healthy",
    "Tomato_Bacterial_spot",
    "Tomato_Early_blight",
    "Tomato_Late_blight",
    "Tomato_Leaf_Mold",
    "Tomato_Septoria_leaf_spot",
    "Tomato_Spider_mites_Two_spotted_spider_mite",
    "Tomato__Target_Spot",
    "Tomato__Tomato_YellowLeaf__Curl_Virus",
    "Tomato__Tomato_mosaic_virus",
    "Tomato_healthy",
]

HEALTHY_LABELS = {"Pepper__bell___healthy", "Potato___healthy", "Tomato_healthy"}

DEMO_MODE = not MODEL_PATH.exists()

_model = None


def _load():
    global _model
    import tensorflow as tf
    print("Loading PlantVillage model...")
    _model = tf.keras.models.load_model(str(MODEL_PATH), compile=False)
    print(f"PlantVillage model ready. {len(CLASS_NAMES)} classes.")


def classify_plantvillage(image_bytes: bytes) -> dict:
    global _model

    if DEMO_MODE:
        scores = [random.random() for _ in CLASS_NAMES]
        total = sum(scores)
        scores = [s / total for s in scores]
        i = scores.index(max(scores))
        return {
            "label": CLASS_NAMES[i],
            "confidence": round(scores[i], 4),
            "healthy": CLASS_NAMES[i] in HEALTHY_LABELS,
            "all_scores": {CLASS_NAMES[j]: round(scores[j], 4) for j in range(len(CLASS_NAMES))},
            "demo": True,
        }

    if _model is None:
        _load()

    img = Image.open(BytesIO(image_bytes)).convert("RGB").resize((256, 256))
    arr = np.array(img, dtype=np.float32) / 255.0
    arr = np.expand_dims(arr, 0)

    probs = _model.predict(arr, verbose=0)[0]
    i = int(np.argmax(probs))

    return {
        "label": CLASS_NAMES[i],
        "confidence": round(float(probs[i]), 4),
        "healthy": CLASS_NAMES[i] in HEALTHY_LABELS,
        "all_scores": {CLASS_NAMES[j]: round(float(probs[j]), 4) for j in range(len(CLASS_NAMES))},
        "demo": False,
    }
