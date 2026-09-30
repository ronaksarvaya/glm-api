class OcrEngine:
    supported_extensions = {
        ".png", ".jpg", ".jpeg", ".webp", ".tiff", ".bmp", ".tif"
    }
    
    def process(self, image, document_type, filename):
        raise NotImplementedError
