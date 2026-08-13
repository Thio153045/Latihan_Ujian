"""Konversi PDF (bytes) menjadi list gambar PIL, satu per halaman.
Dipakai HANYA oleh jalur fallback AI (lihat modules/gemini_client.py:
parse_questions) ketika parser bawaan tanpa-AI (modules/text_parser.py)
gagal membaca PDF dengan layout tak biasa.
"""

import io

import pymupdf
from PIL import Image


def pdf_to_images(pdf_bytes: bytes, dpi: int = 150):
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    zoom = dpi / 72
    mat = pymupdf.Matrix(zoom, zoom)
    images = []
    for page in doc:
        pix = page.get_pixmap(matrix=mat)
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
        images.append(img)
    doc.close()
    return images
