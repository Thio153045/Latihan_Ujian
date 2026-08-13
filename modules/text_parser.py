"""
Parser PDF soal pilihan ganda TANPA AI — murni berbasis library PDF:
- pdfplumber untuk membaca teks & posisi (koordinat) tiap elemen.
- PyMuPDF (pymupdf) untuk merender potongan gambar (tabel/grafik/diagram)
  yang muncul mendukung suatu soal.

Tidak ada panggilan API/kuota AI sama sekali di modul ini. Cocok untuk PDF
dengan layout mirip format SNPDB: nomor soal pada barisnya sendiri, diikuti
teks soal, lalu opsi (A)-(D); tabel/gambar pendukung (bila ada) dirender
sebagai gambar tepat sebelum soal yang membutuhkannya.

Jika sebuah PDF punya layout yang jauh berbeda dan parser ini gagal membaca
sebagian soal dengan baik, guru tetap bisa menyunting manual di halaman
Upload Soal, atau memakai tombol fallback "Proses dengan AI" (lihat
modules/gemini_client.py) yang memang memakai kuota tapi lebih toleran
terhadap layout tak biasa.
"""

import io
import re

import pdfplumber
import pymupdf
from PIL import Image

QNUM_RE = re.compile(r"^\d{1,2}\.$")
MULTI_RE = re.compile(r"Pilihlah\s*(\d+)\s*Jawaban\s*Benar", re.IGNORECASE)
OPTION_RE = re.compile(r"\(([A-D])\)\s*(.*?)(?=\n?\([A-D]\)|\Z)", re.S)

RENDER_DPI = 200
IMAGE_PADDING = 3  # poin, sedikit padding di sekeliling gambar hasil crop


def parse_pdf(pdf_bytes: bytes) -> list:
    """Mengembalikan list of dict soal. Tiap dict punya key tambahan
    "image": PIL.Image atau None, berisi potongan tabel/grafik pendukung
    soal tsb (jika terdeteksi)."""
    questions = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        fitz_doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        zoom = RENDER_DPI / 72
        mat = pymupdf.Matrix(zoom, zoom)

        for page_idx, page in enumerate(pdf.pages):
            words = page.extract_words()
            q_tokens = sorted(
                {(w["top"], w["text"]) for w in words if QNUM_RE.match(w["text"])},
                key=lambda x: x[0],
            )
            if not q_tokens:
                continue

            images = sorted(page.images, key=lambda im: im["top"])
            page_w, page_h = page.width, page.height

            for i, (q_top, q_label) in enumerate(q_tokens):
                try:
                    q_num = int(q_label.rstrip("."))
                except ValueError:
                    continue

                prev_boundary = q_tokens[i - 1][0] if i > 0 else 0
                next_boundary = q_tokens[i + 1][0] if i + 1 < len(q_tokens) else page_h

                # Gambar pendukung = gambar terdekat SEBELUM soal ini, yang
                # muncul setelah batas soal sebelumnya (supaya tidak salah
                # ambil logo header atau gambar milik soal lain).
                supporting_image = None
                for im in images:
                    if prev_boundary <= im["top"] < q_top:
                        supporting_image = im

                crop = page.within_bbox((0, max(q_top - 1, 0), page_w, next_boundary - 1),
                                          relative=False, strict=False)
                block_text = crop.extract_text() or ""

                q_data = _parse_block(q_num, block_text)
                if q_data is None:
                    continue  # gagal parsing (mis. soal terpotong lintas halaman)

                q_data["image"] = (
                    _crop_page_image(fitz_doc, page_idx, mat, supporting_image)
                    if supporting_image is not None else None
                )
                questions.append(q_data)

        fitz_doc.close()

    questions.sort(key=lambda q: q["number"])
    return questions


def _parse_block(q_num: int, block_text: str):
    lines = block_text.strip().split("\n")
    if not lines:
        return None
    if QNUM_RE.match(lines[0].strip()):
        lines = lines[1:]
    body = "\n".join(lines).strip()
    if not body:
        return None

    options = {}
    for m in OPTION_RE.finditer(body):
        letter, text = m.group(1), m.group(2).strip().replace("\n", " ")
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            options[letter] = text

    if len(options) < 2:
        return None  # kemungkinan soal terpotong / lintas halaman

    first_option_pos = body.find("(A)")
    question_text = body[:first_option_pos].strip() if first_option_pos != -1 else body
    question_text = re.sub(r"\s+", " ", question_text).strip()

    multi_match = MULTI_RE.search(question_text)
    multi_answer = bool(multi_match)
    n_correct = int(multi_match.group(1)) if multi_match else 1

    return {
        "number": q_num,
        "question": question_text,
        "options": {letter: options.get(letter, "") for letter in ["A", "B", "C", "D"]},
        "multi_answer": multi_answer,
        "n_correct": n_correct,
    }


def _crop_page_image(fitz_doc, page_idx, mat, im_bbox):
    page = fitz_doc[page_idx]
    rect = pymupdf.Rect(
        max(im_bbox["x0"] - IMAGE_PADDING, 0),
        max(im_bbox["top"] - IMAGE_PADDING, 0),
        min(im_bbox["x1"] + IMAGE_PADDING, page.rect.width),
        min(im_bbox["bottom"] + IMAGE_PADDING, page.rect.height),
    )
    pix = page.get_pixmap(matrix=mat, clip=rect)
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
