import time
from .base import OcrEngine

class ExistingOcrEngine(OcrEngine):
    def process(self, image, document_type, filename):
        start_time = time.time()
        
        # We will import run_ocr from app to avoid moving all tesseract code
        # However, to avoid circular imports, we import it inside the method
        import app
        
        text = app.run_ocr(image)
        
        processing_time = time.time() - start_time
        
        return {
            "raw_text": text,
            "clean_text": text,
            "processing_time": processing_time,
            "ocr_engine": "existing",
            "ocr_model": "tesseract",
            "ocr_status": "completed"
        }
