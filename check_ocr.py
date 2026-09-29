from app import run_ocr, IMAGE_DIR
from PIL import Image
import os

files = [
    "ANIKET-pan.png", 
    "danish ahmed-pan.png", 
    "deshpande-pan.png", 
    "parth-pan.png", 
    "Screenshot 2026-08-31 180238.png", # maybe NIRMALA?
    "Screenshot 2026-08-31 180304.png", # maybe CHIRAG?
]
for filename in files:
    path = os.path.join(IMAGE_DIR, filename)
    if os.path.exists(path):
        print(f"=== {filename} ===")
        with Image.open(path) as img:
            print(run_ocr(img))
        print("="*40)
