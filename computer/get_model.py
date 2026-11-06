"""
Downloads the 38-class PlantVillage MobileNetV2 model from Hugging Face.
Run once:  python get_model.py
"""
from pathlib import Path
from huggingface_hub import snapshot_download
import json

DEST = Path(__file__).parent
MODEL_DIR = DEST / "model"
LABELS_PATH = DEST / "labels.txt"

PLANTVILLAGE_LABELS = [
    "Apple___Apple_scab", "Apple___Black_rot", "Apple___Cedar_apple_rust", "Apple___healthy",
    "Blueberry___healthy", "Cherry___Powdery_mildew", "Cherry___healthy",
    "Corn___Cercospora_leaf_spot", "Corn___Common_rust", "Corn___Northern_Leaf_Blight", "Corn___healthy",
    "Grape___Black_rot", "Grape___Esca", "Grape___Leaf_blight", "Grape___healthy",
    "Orange___Haunglongbing", "Peach___Bacterial_spot", "Peach___healthy",
    "Pepper___Bacterial_spot", "Pepper___healthy",
    "Potato___Early_blight", "Potato___Late_blight", "Potato___healthy",
    "Raspberry___healthy", "Soybean___healthy", "Squash___Powdery_mildew",
    "Strawberry___Leaf_scorch", "Strawberry___healthy",
    "Tomato___Bacterial_spot", "Tomato___Early_blight", "Tomato___Late_blight",
    "Tomato___Leaf_Mold", "Tomato___Septoria_leaf_spot",
    "Tomato___Spider_mites", "Tomato___Target_Spot",
    "Tomato___Tomato_Yellow_Leaf_Curl_Virus", "Tomato___Tomato_mosaic_virus", "Tomato___healthy",
]

print("Downloading model (this may take a minute)...")
local = snapshot_download(
    repo_id="linkanjarad/mobilenet_v2_1.0_224-plant-disease-identification",
    local_dir=str(MODEL_DIR),
    ignore_patterns=["runs/*", "*.tfevents*"],
)
print(f"Model saved to: {MODEL_DIR}")

LABELS_PATH.write_text("\n".join(PLANTVILLAGE_LABELS) + "\n")
print(f"Labels saved to: {LABELS_PATH}")

# Fix renamed class in preprocessor config (old name breaks newer transformers)
import json
pp_path = MODEL_DIR / "preprocessor_config.json"
with open(pp_path) as f:
    pp = json.load(f)
if pp.get("image_processor_type") == "MobileNetV2FeatureExtractor":
    pp["image_processor_type"] = "MobileNetV2ImageProcessor"
    with open(pp_path, "w") as f:
        json.dump(pp, f, indent=2)
    print("Patched preprocessor_config.json for newer transformers.")

print("\nDone. Restart the server to use the real model.")
