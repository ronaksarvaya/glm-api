import os
from .glm_ocr import GlmOcrEngine
from .existing_ocr import ExistingOcrEngine
from .paddle_ocr import PaddleOcrEngine

def get_ocr_engine():
    engine_type = os.environ.get("OCR_ENGINE", "existing").strip().lower()
    
    if engine_type == "paddle":
        return PaddleOcrEngine()
    elif engine_type == "glm_ocr":
        return GlmOcrEngine()
    
    return ExistingOcrEngine()

def print_debug_info(filename, document_type, result, fields):
    if os.environ.get("OCR_DEBUG", "false").lower() != "true":
        return
        
    engine = result.get("ocr_engine")
    model = result.get("ocr_model")
    raw = result.get("raw_text", "")
    clean = result.get("clean_text", "")
    proc_time = result.get("processing_time", 0.0)
    
    print("=" * 60)
    print("OCR JOB START")
    print("=" * 60)
    print(f"Image       : {filename}")
    print(f"Type        : {document_type}")
    print(f"Engine      : {engine}")
    print(f"Model       : {model}")
    print()
    print(f"Processing time: {proc_time:.2f} seconds")
    print()
    print("-" * 60)
    print(f"RAW {engine.upper()} OUTPUT")
    print("-" * 60)
    try:
        print(raw)
    except UnicodeEncodeError:
        print(raw.encode('ascii', 'replace').decode('ascii'))
    print()
    print("-" * 60)
    print("CLEANED OCR OUTPUT")
    print("-" * 60)
    print()
    try:
        print(clean)
    except UnicodeEncodeError:
        print(clean.encode('ascii', 'replace').decode('ascii'))
    print()
    print("-" * 60)
    print("EXTRACTED FIELDS")
    print("-" * 60)
    print()
    for k, v in fields.items():
        print(f"{k.ljust(15)} : {v}")
    print()
    print("=" * 60)
    print("OCR JOB COMPLETE")
    print("=" * 60)
