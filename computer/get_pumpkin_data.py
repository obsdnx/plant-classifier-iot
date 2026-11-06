"""
Downloads the pumpkin leaf disease dataset from Roboflow and
organises it into computer/data/pumpkin/ ready for train.py.

Setup (one time):
  1. Create a free account at https://roboflow.com
  2. Go to https://app.roboflow.com  → top-right avatar → Settings → Roboflow API
  3. Copy your Private API Key
  4. Run:  python get_pumpkin_data.py --api-key YOUR_KEY_HERE
"""

import argparse, shutil
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--api-key", required=True, help="Your Roboflow private API key")
args = parser.parse_args()

BASE     = Path(__file__).parent
DATA_DIR = BASE / "data" / "pumpkin"

# Install roboflow SDK if needed
import subprocess, sys
subprocess.check_call([sys.executable, "-m", "pip", "install", "roboflow", "-q"])

from roboflow import Roboflow

print("Connecting to Roboflow...")
rf = Roboflow(api_key=args.api_key)

# Pumpkin Disease dataset — CC BY 4.0
# https://universe.roboflow.com/miskat-vxtfl/pumpkin-disease-1
project = rf.workspace("miskat-vxtfl").project("pumpkin-disease-1")
version  = project.version(1)

print("Downloading dataset (classification format)...")
dataset  = version.download("folder", location=str(DATA_DIR.parent / "roboflow_raw"))

raw_dir = Path(dataset.location)
print(f"Downloaded to: {raw_dir}")
print("Contents:", list(raw_dir.iterdir()))

# Roboflow 'folder' format puts images in train/valid/test/<class>/
# Merge all splits into data/pumpkin/<class>/
print(f"\nOrganising into {DATA_DIR} ...")
DATA_DIR.mkdir(parents=True, exist_ok=True)

moved = 0
for split in ("train", "valid", "test"):
    split_dir = raw_dir / split
    if not split_dir.exists():
        continue
    for cls_dir in split_dir.iterdir():
        if not cls_dir.is_dir():
            continue
        dest = DATA_DIR / cls_dir.name
        dest.mkdir(exist_ok=True)
        for img in cls_dir.iterdir():
            shutil.copy2(img, dest / img.name)
            moved += 1

print(f"Moved {moved} images.")
print("\nClasses:")
for cls in sorted(DATA_DIR.iterdir()):
    if cls.is_dir():
        count = len(list(cls.glob("*")))
        print(f"  {cls.name}: {count} images")

print("\nDone. Now run:  python train.py")
