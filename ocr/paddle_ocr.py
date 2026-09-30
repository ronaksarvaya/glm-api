import os
import time
import numpy as np
import fitz  # PyMuPDF
from PIL import Image
from .base import OcrEngine

_paddle_instance = None

def get_paddle_instance():
    global _paddle_instance
    if _paddle_instance is None:
        print("[PADDLE] Initializing PaddleOCR...")
        device = os.environ.get("PADDLE_DEVICE", "cpu").lower()
        use_doc_orientation_classify = os.environ.get("PADDLE_USE_DOC_ORIENTATION", "false").lower() == "true"
        use_doc_unwarping = os.environ.get("PADDLE_USE_DOC_UNWARPING", "false").lower() == "true"
        use_textline_orientation = os.environ.get("PADDLE_USE_TEXTLINE_ORIENTATION", "false").lower() == "true"
        
        from paddleocr import PaddleOCR
        _paddle_instance = PaddleOCR(
            lang="en",
            enable_mkldnn=False,
            use_doc_orientation_classify=use_doc_orientation_classify,
            use_doc_unwarping=use_doc_unwarping,
            use_textline_orientation=use_textline_orientation
        )
        print("[PADDLE] Model loaded successfully")
        print(f"[PADDLE] Device: {device.upper()}")
    return _paddle_instance

class PaddleOcrEngine(OcrEngine):
    supported_extensions = {
        ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif", ".pdf"
    }

    def process(self, image, document_type, filename):
        start_time = time.time()
        print(f"[PADDLE] Processing: {filename}")
        print("[PADDLE] File type: image")
        print("[PADDLE] Starting OCR...")
        
        paddle = get_paddle_instance()
        
        # Convert PIL Image to BGR numpy array for PaddleOCR
        img_array = np.array(image.convert('RGB'))
        img_array = img_array[:, :, ::-1].copy() # RGB to BGR
        
        result = paddle.ocr(img_array)
        
        print("[PADDLE] Detection completed")
        print("[PADDLE] Recognition completed")
        
        text_blocks = []
        raw_text_parts = []
        
        if result and len(result) > 0 and result[0]:
            for line in result[0]:
                box = line[0]
                text, confidence = line[1]
                text_blocks.append(text)
                raw_text_parts.append(f"{text} (conf: {confidence:.2f})")
                
        clean_text = "\n".join(text_blocks)
        raw_text = "\n".join(raw_text_parts)
        
        processing_time = time.time() - start_time
        print(f"[PADDLE] Processing time: {processing_time:.2f}s")
        print(f"[PADDLE] Text blocks: {len(text_blocks)}")
        
        return {
            "ocr_engine": "paddle",
            "ocr_model": "paddleocr_v3",
            "raw_text": raw_text,
            "clean_text": clean_text,
            "processing_time": processing_time
        }
    
    def process_pdf(self, pdf_bytes, filename):
        start_time = time.time()
        print(f"[PADDLE] Processing: {filename}")
        
        paddle = get_paddle_instance()
        
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as e:
            raise ValueError(f"Failed to read PDF: {e}")
            
        page_count = len(doc)
        print(f"[PADDLE] Pages: {page_count}")
        
        pages_results = []
        full_clean_text = []
        full_raw_text = []
        
        pdf_render_time = 0
        ocr_total_time = 0
        
        for i in range(page_count):
            print(f"[PADDLE] Page {i+1}/{page_count}")
            page_start = time.time()
            
            # Render page to image
            render_start = time.time()
            page = doc.load_page(i)
            pix = page.get_pixmap(dpi=200)
            if pix.alpha:
                mode = "RGBA"
            else:
                mode = "RGB"
            image = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
            render_time = time.time() - render_start
            pdf_render_time += render_time
            
            # OCR
            ocr_start = time.time()
            img_array = np.array(image.convert('RGB'))
            img_array = img_array[:, :, ::-1].copy() # RGB to BGR
            
            result = paddle.ocr(img_array)
            
            text_blocks = []
            raw_text_parts = []
            if result and len(result) > 0 and result[0]:
                for line in result[0]:
                    text, confidence = line[1]
                    text_blocks.append(text)
                    raw_text_parts.append(f"{text} (conf: {confidence:.2f})")
                    
            clean_text = "\n".join(text_blocks)
            raw_text = "\n".join(raw_text_parts)
            
            ocr_time = time.time() - ocr_start
            ocr_total_time += ocr_time
            
            page_time = time.time() - page_start
            print(f"[PADDLE] Page {i+1} completed in {page_time:.2f}s")
            
            pages_results.append({
                "page": i + 1,
                "text": clean_text
            })
            full_clean_text.append(clean_text)
            full_raw_text.append(raw_text)
            
        total_time = time.time() - start_time
        print(f"[PADDLE] Total processing time: {total_time:.2f}s")
        print(f"[PADDLE] PDF rendering: {pdf_render_time:.2f}s")
        print(f"[PADDLE] OCR: {ocr_total_time:.2f}s")
        
        return {
            "success": True,
            "filename": filename,
            "type": "pdf",
            "pages": pages_results,
            "full_text": "\n\n".join(full_clean_text),
            "raw_text": "\n\n".join(full_raw_text),
            "processing_time": total_time,
            "pdf_rendering_time": pdf_render_time,
            "ocr_time": ocr_total_time,
            "page_count": page_count
        }

    def process_file(self, file_path, document_type, filename):
        start_time = time.time()
        print(f"[PADDLE] Processing: {filename}")
        
        is_pdf = filename.lower().endswith('.pdf')
        print(f"[PADDLE] File type: {'PDF' if is_pdf else 'image'}")
        print("[PADDLE] Starting OCR...")
        
        paddle = get_paddle_instance()
        
        # Pass file path directly to PaddleOCR
        result = paddle.ocr(file_path)
        
        print("[PADDLE] Detection completed")
        print("[PADDLE] Recognition completed")
        
        text_blocks = []
        raw_text_parts = []
        pages_results = []
        
        if result:
            for page_idx, page_res in enumerate(result):
                if page_res:
                    page_text_blocks = []
                    
                    if isinstance(page_res, dict) and 'rec_texts' in page_res:
                        texts = page_res.get('rec_texts', [])
                        scores = page_res.get('rec_scores', [])
                        for i in range(len(texts)):
                            text = texts[i]
                            confidence = scores[i] if i < len(scores) else 0.0
                            text_blocks.append(text)
                            page_text_blocks.append(text)
                            raw_text_parts.append(f"{text} (conf: {confidence:.2f})")
                    else:
                        for line in page_res:
                            if len(line) == 2 and isinstance(line[1], tuple):
                                box = line[0]
                                text, confidence = line[1]
                                text_blocks.append(text)
                                page_text_blocks.append(text)
                                raw_text_parts.append(f"{text} (conf: {confidence:.2f})")
                            
                    pages_results.append({
                        "page": page_idx + 1,
                        "text": "\n".join(page_text_blocks)
                    })
                
        clean_text = "\n".join(text_blocks)
        raw_text = "\n".join(raw_text_parts)
        
        processing_time = time.time() - start_time
        print(f"[PADDLE] Processing time: {processing_time:.2f}s")
        if is_pdf:
            print(f"[PADDLE] Pages processed: {len(result) if result else 0}")
        print(f"[PADDLE] Text blocks: {len(text_blocks)}")
        
        if is_pdf:
            return {
                "success": True,
                "filename": filename,
                "type": "pdf",
                "pages": pages_results,
                "full_text": clean_text,
                "raw_text": raw_text,
                "processing_time": processing_time
            }
        else:
            return {
                "ocr_engine": "paddle",
                "ocr_model": "paddleocr_v3",
                "raw_text": raw_text,
                "clean_text": clean_text,
                "processing_time": processing_time
            }
