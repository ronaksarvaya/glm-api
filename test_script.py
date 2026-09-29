import requests
import os

images_dir = "d:/ocr-server/images/images"
image_file = None
for f in os.listdir(images_dir):
    if f.endswith((".jpg", ".jpeg", ".png")):
        image_file = os.path.join(images_dir, f)
        break

if image_file:
    print(f"Testing with {image_file}")
    with open(image_file, "rb") as f:
        r = requests.post("http://127.0.0.1:5000/ocr/test", files={"file": f})
    print(r.status_code)
    print(r.json())
else:
    print("No image found.")
