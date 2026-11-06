"""
Fine-tunes MobileNetV2 on pumpkin leaf disease data.

Dataset setup (do this once before running):
  1. Go to https://data.mendeley.com/datasets/7397w9h5tb/1
  2. Click Download All (free Mendeley account required)
  3. Unzip into:  computer/data/pumpkin/
     Structure should be:
       data/pumpkin/Healthy/
       data/pumpkin/Downy Mildew/
       data/pumpkin/Leaf Curl/
       data/pumpkin/Mosaic/
       data/pumpkin/Red Beetle/

Then run:  python train.py
The fine-tuned model overwrites computer/model/ and labels.txt.
"""

import os, shutil, zipfile, json
from pathlib import Path
from PIL import Image
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset, random_split
from torchvision import transforms
from transformers import MobileNetV2ForImageClassification, MobileNetV2ImageProcessor
from torch.optim import AdamW
from torch.optim.lr_scheduler import CosineAnnealingLR
import numpy as np

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE = Path(__file__).parent
MODEL_DIR = BASE / "model"
LABELS_PATH = BASE / "labels.txt"

# Use Kaggle cache if local data dir not present
_KAGGLE_CACHE = Path.home() / ".cache/kagglehub/datasets/tahmidmir/pumpkin-leaf-diseases-dataset-from-bangladesh/versions/1/Pumpkin Leaf Diseases Dataset From Bangladesh/Original Dataset"
DATA_DIR = BASE / "data" / "pumpkin"
if not DATA_DIR.exists() and _KAGGLE_CACHE.exists():
    DATA_DIR = _KAGGLE_CACHE

# ── Config ─────────────────────────────────────────────────────────────────────
EPOCHS      = 15
BATCH_SIZE  = 32
LR          = 2e-4
IMAGE_SIZE  = 224
VAL_SPLIT   = 0.15
DEVICE      = "mps" if torch.backends.mps.is_available() else \
              "cuda" if torch.cuda.is_available() else "cpu"

print(f"Using device: {DEVICE}")

# ── Check dataset ──────────────────────────────────────────────────────────────
if not DATA_DIR.exists():
    print(f"\nERROR: Dataset not found at {DATA_DIR}")
    print("Download from: https://data.mendeley.com/datasets/7397w9h5tb/1")
    print("Unzip into: computer/data/pumpkin/  (subfolders = class names)")
    raise SystemExit(1)

classes = sorted([d.name for d in DATA_DIR.iterdir() if d.is_dir()])
print(f"Classes found: {classes}")

# ── Augmentation — heavy, for real-world field photos ─────────────────────────
train_tf = transforms.Compose([
    transforms.Resize(256),
    transforms.RandomResizedCrop(IMAGE_SIZE, scale=(0.6, 1.0)),
    transforms.RandomHorizontalFlip(),
    transforms.RandomVerticalFlip(),
    transforms.RandomRotation(30),
    transforms.ColorJitter(brightness=0.4, contrast=0.4, saturation=0.3, hue=0.1),
    transforms.RandomGrayscale(p=0.05),
    transforms.GaussianBlur(kernel_size=5, sigma=(0.1, 2.0)),
    transforms.RandomPerspective(distortion_scale=0.3, p=0.3),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5]),
    transforms.RandomErasing(p=0.2, scale=(0.02, 0.1)),  # hide small patches
])

val_tf = transforms.Compose([
    transforms.Resize(256),
    transforms.CenterCrop(IMAGE_SIZE),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5]),
])

# ── Dataset ────────────────────────────────────────────────────────────────────
class LeafDataset(Dataset):
    def __init__(self, root, classes, transform=None):
        self.transform = transform
        raw = []
        for i, cls in enumerate(classes):
            cls_dir = root / cls
            for ext in ("*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG"):
                for p in cls_dir.glob(ext):
                    raw.append((p, i))

        print(f"  Loading {len(raw)} images into RAM...")
        self.images, self.labels = [], []
        for p, label in raw:
            try:
                self.images.append(Image.open(p).convert("RGB"))
                self.labels.append(label)
            except Exception:
                pass
        print(f"  {len(self.images)} images cached across {len(classes)} classes")

    def __len__(self):
        return len(self.images)

    def __getitem__(self, idx):
        img = self.images[idx]
        if self.transform:
            img = self.transform(img)
        return img, self.labels[idx]

full_ds = LeafDataset(DATA_DIR, classes, transform=None)
n_val   = int(len(full_ds) * VAL_SPLIT)
n_train = len(full_ds) - n_val
train_indices, val_indices = random_split(range(len(full_ds)), [n_train, n_val],
                                           generator=torch.Generator().manual_seed(42))

class TransformDataset(Dataset):
    def __init__(self, base_ds, indices, transform):
        self.base = base_ds
        self.indices = list(indices)
        self.transform = transform
    def __len__(self):
        return len(self.indices)
    def __getitem__(self, idx):
        img = self.base.images[self.indices[idx]]
        return self.transform(img), self.base.labels[self.indices[idx]]

train_ds = TransformDataset(full_ds, train_indices, train_tf)
val_ds   = TransformDataset(full_ds, val_indices,   val_tf)

train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True,  num_workers=0, pin_memory=False)
val_loader   = DataLoader(val_ds,   batch_size=BATCH_SIZE, shuffle=False, num_workers=0, pin_memory=False)

# ── Model — load pretrained MobileNetV2, replace classifier head ───────────────
print("\nLoading pretrained MobileNetV2...")
model = MobileNetV2ForImageClassification.from_pretrained(
    str(MODEL_DIR),
    num_labels=len(classes),
    ignore_mismatched_sizes=True,
)
model = model.to(DEVICE)

optimizer = AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
scheduler = CosineAnnealingLR(optimizer, T_max=EPOCHS)
criterion = nn.CrossEntropyLoss(label_smoothing=0.1)

# ── Training loop ──────────────────────────────────────────────────────────────
best_val_acc = 0.0
best_state   = None

for epoch in range(1, EPOCHS + 1):
    model.train()
    total_loss, correct, total = 0.0, 0, 0
    for imgs, labels in train_loader:
        imgs, labels = imgs.to(DEVICE), labels.to(DEVICE)
        optimizer.zero_grad()
        out  = model(pixel_values=imgs).logits
        loss = criterion(out, labels)
        loss.backward()
        optimizer.step()
        total_loss += loss.item() * imgs.size(0)
        correct    += (out.argmax(1) == labels).sum().item()
        total      += imgs.size(0)
    scheduler.step()

    model.eval()
    val_correct, val_total = 0, 0
    with torch.no_grad():
        for imgs, labels in val_loader:
            imgs, labels = imgs.to(DEVICE), labels.to(DEVICE)
            out = model(pixel_values=imgs).logits
            val_correct += (out.argmax(1) == labels).sum().item()
            val_total   += imgs.size(0)

    train_acc = correct / total
    val_acc   = val_correct / val_total
    print(f"Epoch {epoch:02d}/{EPOCHS}  "
          f"loss={total_loss/total:.4f}  "
          f"train={train_acc:.3f}  val={val_acc:.3f}")

    if val_acc > best_val_acc:
        best_val_acc = val_acc
        best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
        print(f"  ✓ New best val acc: {best_val_acc:.3f}")

# ── Save ───────────────────────────────────────────────────────────────────────
print(f"\nBest val accuracy: {best_val_acc:.3f}")
model.load_state_dict(best_state)

print("Saving model...")
model.save_pretrained(str(MODEL_DIR))

# Update labels
LABELS_PATH.write_text("\n".join(classes) + "\n")
print(f"Labels saved: {classes}")

# Update preprocessor config with correct class names
pp_path = MODEL_DIR / "preprocessor_config.json"
with open(pp_path) as f:
    pp = json.load(f)
pp["image_processor_type"] = "MobileNetV2ImageProcessor"
with open(pp_path, "w") as f:
    json.dump(pp, f, indent=2)

print(f"\nDone. Restart the server — it will now classify pumpkin diseases.")
print(f"Classes: {classes}")
