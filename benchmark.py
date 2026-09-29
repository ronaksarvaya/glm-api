import os
import time
from PIL import Image
from app import run_ocr_detail, IMAGE_DIR, list_image_files


def main():
    names = list_image_files()
    print(f"Benchmarking {len(names)} images...\n")

    upscale2x_skipped = 0
    upscale2x_executed = 0
    per_image_times = []
    results = []

    for name in names:
        path = os.path.join(IMAGE_DIR, name)
        with Image.open(path) as image:
            start = time.perf_counter()
            detail = run_ocr_detail(image)
            elapsed = time.perf_counter() - start

        per_image_times.append(elapsed)
        skipped = detail.get("skipped", [])
        if "upscale2x" in skipped:
            upscale2x_skipped += 1
        else:
            upscale2x_executed += 1

        results.append({
            "filename": name,
            "variant": detail["variant"],
            "score": detail["score"],
            "time": elapsed,
            "upscale2x_skipped": "upscale2x" in skipped,
        })

    total_time = sum(per_image_times)
    avg_time = total_time / len(per_image_times) if per_image_times else 0

    print("=" * 70)
    print("PERFORMANCE RESULTS")
    print("=" * 70)
    print(f"Total images: {len(names)}")
    print(f"Total batch time: {total_time:.2f}s")
    print(f"Average per image: {avg_time:.2f}s")
    print()
    print(f"upscale2x skipped: {upscale2x_skipped}")
    print(f"upscale2x executed: {upscale2x_executed}")
    print()
    print("-" * 70)
    print(f"{'Filename':<40} {'Variant':<12} {'Time':>8} {'Upscale2x':>10}")
    print("-" * 70)
    for r in results:
        skip_label = "SKIPPED" if r["upscale2x_skipped"] else "ran"
        print(f"{r['filename']:<40} {r['variant']:<12} {r['time']:>7.2f}s {skip_label:>10}")
    print("-" * 70)


if __name__ == "__main__":
    main()
