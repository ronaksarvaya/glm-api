import os
from PIL import Image
from app import IMAGE_DIR, run_ocr, extract_pan

test_cases = [
    "ANIKET-pan.png",
    "danish ahmed-pan.png",
    "deshpande-pan.png",
    "parth-pan.png"
]

for filename in test_cases:
    print(f"=== {filename} ===")
    path = os.path.join(IMAGE_DIR, filename)
    if os.path.exists(path):
        with Image.open(path) as img:
            text = run_ocr(img)
            result = extract_pan(text)
            print(result)
    else:
        print("File not found")
    print("="*40)
