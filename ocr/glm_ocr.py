import os
import time
import base64
import requests
import re
from io import BytesIO
from .base import OcrEngine

class GlmOcrEngine(OcrEngine):
    def __init__(self):
        self.base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        self.model = os.environ.get("GLM_OCR_MODEL", "glm-ocr:latest")
        self.timeout = int(os.environ.get("GLM_OCR_TIMEOUT", "180"))
        self.num_predict = int(os.environ.get("GLM_OCR_NUM_PREDICT", "512"))
        self.temperature = float(os.environ.get("GLM_OCR_TEMPERATURE", "0"))
        self.debug = os.environ.get("OCR_DEBUG", "false").lower() == "true"

    def is_available(self):
        try:
            r = requests.get(self.base_url, timeout=5)
            if r.status_code != 200:
                return False
            r_tags = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if r_tags.status_code == 200:
                models = [m["name"] for m in r_tags.json().get("models", [])]
                if self.model in models:
                    return True
            return False
        except Exception:
            return False

    def process(self, image, document_type, filename):
        start_time = time.time()
        
        prompt_map = {
            "PAN": "pan.txt",
            "PASSPORT_FRONT": "passport_front.txt",
            "PASSPORT_BACK": "passport_back.txt",
        }
        prompt_file = prompt_map.get(document_type, "generic.txt")
        prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts", prompt_file)
        
        try:
            with open(prompt_path, "r") as f:
                prompt_text = f.read()
        except Exception:
            prompt_text = "Please read the visible text in this document."
            
        buffered = BytesIO()
        image = image.convert("RGB")
        image.save(buffered, format="JPEG")
        img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
        
        payload = {
            "model": self.model,
            "prompt": prompt_text,
            "images": [img_str],
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.num_predict
            }
        }
        
        try:
            if self.debug:
                print("Sending image to Ollama...")
            r = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=self.timeout)
            r.raise_for_status()
            resp = r.json()
            raw_output = resp.get("response", "")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"GLM-OCR request failed: {str(e)}")
            
        processing_time = time.time() - start_time
        if self.debug:
            print(f"Ollama response received.\nProcessing time: {processing_time:.2f} seconds")
        
        clean_output = self._clean_output(raw_output)
        
        return {
            "raw_text": raw_output,
            "clean_text": clean_output,
            "processing_time": processing_time,
            "ocr_engine": "glm_ocr",
            "ocr_model": self.model,
            "ocr_status": "completed"
        }
        
    def _clean_output(self, text):
        lines = text.splitlines()
        cleaned_lines = []
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                cleaned_lines.append("")
                i += 1
                continue
                
            block = []
            j = i
            while j < len(lines) and lines[j].strip():
                block.append(lines[j].strip())
                j += 1
            
            block_text = "\n".join(block)
            
            # Simple repetition removal for blocks
            # Look ahead to see if the next block is identical
            k = j
            while k < len(lines) and not lines[k].strip():
                k += 1
            
            next_block = []
            l = k
            while l < len(lines) and lines[l].strip():
                next_block.append(lines[l].strip())
                l += 1
                
            next_block_text = "\n".join(next_block)
            
            if block_text and block_text == next_block_text:
                # skip this block, it's a duplicate
                pass
            else:
                cleaned_lines.extend(block)
                if j < len(lines):
                    cleaned_lines.append("")
            
            i = j if j > i else i + 1
            
        return "\n".join(cleaned_lines).strip()
