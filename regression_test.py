import os
from PIL import Image
import app
from app import (
    IMAGE_DIR,
    list_image_files,
    run_ocr_detail,
    extract_fields,
    _original_is_authoritative,
    OCR_PREFER_ORIGINAL_WITH_MRZ,
)

PASSPORT_FRONT_GATE = [
    "ANIKET-pass.png",
    "parth-pass.png",
    "ruchi-pass.png",
    "shridhar.png",
]

PASSPORT_FRONT_FIELDS = [
    "passport_number",
    "surname",
    "given_name",
    "date_of_birth",
    "sex",
    "place_of_birth",
    "place_of_issue",
    "date_of_issue",
    "date_of_expiry",
]


def run_baseline():
    """All 6 variants always run. MRZ authority pins to original when valid.

    This simulates the pre-optimization behavior: every preprocessing
    candidate is OCR'd, then the winner is chosen (original if MRZ is
    authoritative, otherwise the highest-scoring variant).
    """
    results = {}
    for name in list_image_files():
        path = os.path.join(IMAGE_DIR, name)
        with Image.open(path) as image:
            detail = run_ocr_detail(image)
            # Force all variants to run by temporarily disabling the skip
            # but keeping MRZ authority for winner selection.
            # We re-run with a flag that forces all variants.
            detail_forced = run_ocr_detail_force_all(image)
        doc_type, fields = extract_fields(detail_forced["text"])
        results[name] = {
            "document_type": doc_type,
            "fields": fields,
            "raw_text": detail_forced["text"],
            "variant": detail_forced["variant"],
        }
    return results


def run_ocr_detail_force_all(image):
    """Run all variants regardless of MRZ authority, then select winner
    using the same rules as run_ocr_detail (original if MRZ authoritative,
    else best score)."""
    from app import build_ocr_candidates, score_ocr_text
    candidates = build_ocr_candidates(image)
    results = {}
    for name in candidates:
        try:
            results[name] = app.pytesseract.image_to_string(
                candidates[name], config=app.OCR_TESSERACT_CONFIG
            )
        except Exception:
            results[name] = ""

    authoritative = bool(
        OCR_PREFER_ORIGINAL_WITH_MRZ
        and _original_is_authoritative(results["original"])
    )
    scores = {n: score_ocr_text(t) for n, t in results.items()}
    best_name = "original" if authoritative else max(scores, key=lambda n: scores[n])
    return {
        "variant": best_name,
        "score": scores[best_name],
        "text": results[best_name],
        "original_text": results["original"],
        "skipped": [],
        "all": {n: {"score": scores[n], "text": t} for n, t in results.items()},
    }


def run_optimized():
    """Current adaptive code: skip upscale2x when MRZ is authoritative."""
    results = {}
    for name in list_image_files():
        path = os.path.join(IMAGE_DIR, name)
        with Image.open(path) as image:
            detail = run_ocr_detail(image)
        doc_type, fields = extract_fields(detail["text"])
        results[name] = {
            "document_type": doc_type,
            "fields": fields,
            "raw_text": detail["text"],
            "variant": detail["variant"],
        }
    return results


def compare_fields(fields_a, fields_b):
    diffs = []
    all_keys = set(fields_a.keys()) | set(fields_b.keys())
    for key in sorted(all_keys):
        if fields_a.get(key) != fields_b.get(key):
            diffs.append(key)
    return diffs


def main():
    print("Running regression test...\n")

    print("[1/3] Running BASELINE (all 6 variants, MRZ authority intact)...")
    baseline = run_baseline()
    print(f"      Done. {len(baseline)} images processed.")

    print("[2/3] Running OPTIMIZED (upscale2x skipped when MRZ valid)...")
    optimized = run_optimized()
    print(f"      Done. {len(optimized)} images processed.")

    print("[3/3] Comparing results...\n")

    # --- Passport Front gate ---
    print("=" * 70)
    print("PASSPORT FRONT REGRESSION GATE")
    print("=" * 70)
    total_fields = 0
    unchanged_fields = 0
    regressions = []

    for name in PASSPORT_FRONT_GATE:
        if name not in baseline:
            print(f"  MISSING: {name}")
            continue

        b = baseline[name]
        o = optimized[name]

        type_match = b["document_type"] == o["document_type"]
        field_diffs = compare_fields(b["fields"], o["fields"])

        for field in PASSPORT_FRONT_FIELDS:
            total_fields += 1
            if field not in field_diffs:
                unchanged_fields += 1

        status = "PASS" if type_match and not field_diffs else "FAIL"
        print(f"  {name}: {status}")
        print(f"    doc_type: {b['document_type']} (match={type_match})")
        if field_diffs:
            print(f"    field diffs: {field_diffs}")
            regressions.append(name)
        if not type_match:
            regressions.append(name)

    print(f"\n  Fields unchanged: {unchanged_fields}/{total_fields}")
    print(f"  Regressions: {len(regressions)}")

    # --- Full batch ---
    print()
    print("=" * 70)
    print("FULL 20-IMAGE REGRESSION BATCH")
    print("=" * 70)
    type_changes = 0
    field_regressions = 0

    for name in sorted(baseline.keys()):
        b = baseline[name]
        o = optimized[name]

        if b["document_type"] != o["document_type"]:
            type_changes += 1
            print(f"  TYPE CHANGE: {name}: {b['document_type']} -> {o['document_type']}")

        diffs = compare_fields(b["fields"], o["fields"])
        if diffs:
            field_regressions += 1
            print(f"  FIELD REGRESSION: {name}: {diffs}")

    print(f"\n  Document-type changes: {type_changes}")
    print(f"  Field regressions: {field_regressions}")

    # --- Summary ---
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    gate_pass = unchanged_fields == total_fields and len(regressions) == 0
    batch_pass = type_changes == 0 and field_regressions == 0

    print(f"  Passport Front gate: {'PASS' if gate_pass else 'FAIL'} ({unchanged_fields}/{total_fields} unchanged)")
    print(f"  Full batch:           {'PASS' if batch_pass else 'FAIL'}")
    print(f"  Overall:              {'PASS' if gate_pass and batch_pass else 'FAIL'}")

    return 0 if (gate_pass and batch_pass) else 1


if __name__ == "__main__":
    exit(main())
