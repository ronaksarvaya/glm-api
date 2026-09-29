import os
import tempfile
import unittest
from app import app
import fitz 
from PIL import Image

class TestAPI(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()

    def create_test_image(self, ext='.png'):
        img = Image.new('RGB', (100, 100), color = 'red')
        fd, path = tempfile.mkstemp(suffix=ext)
        os.close(fd)
        img.save(path)
        return path

    def create_test_pdf(self, pages=1):
        fd, path = tempfile.mkstemp(suffix='.pdf')
        os.close(fd)
        doc = fitz.open()
        for _ in range(pages):
            page = doc.new_page()
            page.insert_text((50, 50), "Test Text")
        doc.save(path)
        doc.close()
        return path

    def test_image_upload(self):
        img_path = self.create_test_image('.png')
        with open(img_path, 'rb') as f:
            data = {
                'image': (f, 'test.png')
            }
            response = self.client.post('/api/v1/ocr', data=data)
        os.remove(img_path)
        
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertTrue(json_data['success'])
        self.assertIn('document_type', json_data)
        self.assertIn('ocr', json_data)

    def test_pdf_upload(self):
        pdf_path = self.create_test_pdf(1)
        with open(pdf_path, 'rb') as f:
            data = {
                'image': (f, 'test.pdf')
            }
            response = self.client.post('/api/v1/ocr', data=data)
        os.remove(pdf_path)
        
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertTrue(json_data['success'])
        self.assertEqual(json_data['file_type'], 'pdf')
        self.assertEqual(len(json_data['pages']), 1)

    def test_multipage_pdf_upload(self):
        pdf_path = self.create_test_pdf(3)
        with open(pdf_path, 'rb') as f:
            data = {
                'image': (f, 'test2.pdf')
            }
            response = self.client.post('/api/v1/ocr', data=data)
        os.remove(pdf_path)
        
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertTrue(json_data['success'])
        self.assertEqual(json_data['file_type'], 'pdf')
        self.assertEqual(len(json_data['pages']), 3)

    def test_unsupported_file(self):
        fd, path = tempfile.mkstemp(suffix='.txt')
        os.close(fd)
        with open(path, 'w') as f:
            f.write("test")
            
        with open(path, 'rb') as f:
            data = {
                'image': (f, 'test.txt')
            }
            response = self.client.post('/api/v1/ocr', data=data)
        os.remove(path)
        
        self.assertEqual(response.status_code, 400)
        json_data = response.get_json()
        self.assertFalse(json_data['success'])
        self.assertEqual(json_data['error']['code'], 'UNSUPPORTED_FILE_TYPE')

if __name__ == '__main__':
    unittest.main()
