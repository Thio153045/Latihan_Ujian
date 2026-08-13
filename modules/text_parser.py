"""
Parser PDF soal pilihan ganda TANPA AI — murni berbasis library PDF:
- pdfplumber untuk membaca teks & posisi (koordinat) tiap elemen.
- PyMuPDF (pymupdf) untuk merender potongan gambar (tabel/grafik/diagram)
  yang muncul mendukung suatu soal.

Tidak ada panggilan API/kuota AI sama sekali di modul ini. Mendukung dua
format penulisan opsi jawaban sekaligus:
  - "(A) teks opsi"   -> format lama (mis. PDF SNPDB)
  - "A. teks opsi"     -> format baru (mis. PDF TPA MAN Insan Cendekia)
dengan jumlah opsi fleksibel (A-D, A-E, dst — tidak dihardcode 4 opsi).
Tabel/gambar pendukung (bila ada) dirender sebagai gambar tepat sebelum
soal yang membutuhkannya.

Jika sebuah PDF punya layout yang jauh berbeda dari kedua format di atas
dan parser ini gagal membaca sebagian soal dengan baik, guru tetap bisa
menyunting manual di halaman Upload Soal, atau memakai tombol fallback
"Proses dengan AI" (lihat modules/gemini_client.py) yang memang memakai
kuota tapi lebih toleran terhadap layout tak biasa.
"""

import io
import re

import pdfplumber
import pymupdf
from PIL import Image

QNUM_RE = re.compile(r"^\d{1,2}\.$")
QNUM_PREFIX_RE = re.compile(r"^\d{1,2}\.\s+")
MULTI_RE = re.compile(r"Pilihlah\s*(\d+)\s*Jawaban\s*Benar", re.IGNORECASE)

# Huruf opsi didukung sampai H (8 pilihan) — jauh lebih dari cukup untuk
# soal pilihan ganda pada umumnya (biasanya 4-5 opsi), sekaligus menghindari
# regex yang terlalu rakus menangkap huruf acak di tengah kalimat.
LETTER_RANGE = "A-H"
PAREN_OPTION_RE = re.compile(rf"\(([{LETTER_RANGE}])\)\s*(.*?)(?=\n?\([{LETTER_RANGE}]\)|\Z)", re.S)
PERIOD_OPTION_RE = re.compile(rf"(?m)^([{LETTER_RANGE}])\.\s+(.*?)(?=\n[{LETTER_RANGE}]\.\s|\Z)", re.S)

RENDER_DPI = 200
IMAGE_PADDING = 3  # poin, sedikit padding di sekeliling gambar hasil crop


def parse_pdf(pdf_bytes: bytes) -> list:
    """Mengembalikan list of dict soal. Tiap dict punya key tambahan
    "image": PIL.Image atau None, berisi potongan tabel/grafik pendukung
    soal tsb (jika terdeteksi).

    Mendukung soal yang teks/opsinya terpotong lintas halaman (mis. kalimat
    soal di akhir satu halaman, opsi jawabannya baru muncul di awal halaman
    berikutnya) — bukan cuma soal yang selalu utuh dalam satu halaman."""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        fitz_doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        zoom = RENDER_DPI / 72
        mat = pymupdf.Matrix(zoom, zoom)

        # --- Kumpulkan token nomor soal DI SELURUH dokumen (bukan per
        # halaman saja), supaya batas antar-soal bisa melintasi halaman. ---
        global_tokens = []  # list of (page_idx, top, q_num)
        for page_idx, page in enumerate(pdf.pages):
            words = page.extract_words()
            page_tokens = sorted(
                {(w["top"], w["text"]) for w in words if QNUM_RE.match(w["text"])},
                key=lambda x: x[0],
            )
            for top, label in page_tokens:
                try:
                    global_tokens.append((page_idx, top, int(label.rstrip("."))))
                except ValueError:
                    continue

        if not global_tokens:
            fitz_doc.close()
            return []

        last_page_idx = len(pdf.pages) - 1
        last_page_bottom = pdf.pages[last_page_idx].height

        # --- Gambar pendukung: dicari PER HALAMAN (asumsi gambar & soal
        # yang memakainya selalu berada di halaman yang sama — berlaku pada
        # semua contoh yang pernah ditemui; kalaupun tidak, soal tsb cukup
        # tampil tanpa gambar, tidak menggagalkan parsing teksnya). ---
        image_by_number = {}
        for page_idx, page in enumerate(pdf.pages):
            page_tokens = [(top, num) for (p, top, num) in global_tokens if p == page_idx]
            if not page_tokens:
                continue
            images = sorted(page.images, key=lambda im: im["top"])
            for i, (q_top, q_num) in enumerate(page_tokens):
                prev_boundary = page_tokens[i - 1][0] if i > 0 else 0
                supporting_image = None
                for im in images:
                    if prev_boundary <= im["top"] < q_top:
                        supporting_image = im
                if supporting_image is not None:
                    image_by_number[q_num] = _crop_page_image(fitz_doc, page_idx, mat, supporting_image)

        # --- Teks tiap soal: dari posisi soal ini sampai posisi soal
        # berikutnya, walau itu berarti melintasi satu atau lebih halaman. ---
        questions = []
        for i, (page_idx, top, q_num) in enumerate(global_tokens):
            if i + 1 < len(global_tokens):
                end_page_idx, end_top, _ = global_tokens[i + 1]
            else:
                # Soal terakhir di dokumen: ambil sampai akhir halaman
                # terakhir (aman meski ada teks non-soal setelahnya, karena
                # itu tidak akan cocok pola opsi jawaban).
                end_page_idx, end_top = last_page_idx, last_page_bottom

            block_text = _extract_block_text(pdf.pages, page_idx, top, end_page_idx, end_top)
            q_data = _parse_block(q_num, block_text)
            if q_data is None:
                continue
            q_data["image"] = image_by_number.get(q_num)
            questions.append(q_data)

        fitz_doc.close()

    questions.sort(key=lambda q: q["number"])
    return questions


def _extract_block_text(pages, start_page_idx: int, start_top: float,
                         end_page_idx: int, end_top: float) -> str:
    """Ambil teks dari (start_page_idx, start_top) sampai (end_page_idx,
    end_top), termasuk kalau itu berarti melintasi beberapa halaman."""
    parts = []
    if start_page_idx == end_page_idx:
        page = pages[start_page_idx]
        crop = page.within_bbox(
            (0, max(start_top - 1, 0), page.width, max(end_top - 1, start_top)),
            relative=False, strict=False,
        )
        parts.append(crop.extract_text() or "")
    else:
        first_page = pages[start_page_idx]
        crop_first = first_page.within_bbox(
            (0, max(start_top - 1, 0), first_page.width, first_page.height),
            relative=False, strict=False,
        )
        parts.append(crop_first.extract_text() or "")

        for pidx in range(start_page_idx + 1, end_page_idx):
            parts.append(pages[pidx].extract_text() or "")

        last_page = pages[end_page_idx]
        crop_last = last_page.within_bbox(
            (0, 0, last_page.width, max(end_top - 1, 0)),
            relative=False, strict=False,
        )
        parts.append(crop_last.extract_text() or "")

    return "\n".join(p for p in parts if p)


def _parse_block(q_num: int, block_text: str):
    lines = block_text.strip().split("\n")
    if not lines:
        return None
    if QNUM_RE.match(lines[0].strip()):
        # Format lama: nomor soal berdiri sendiri di barisnya sendiri ("1.").
        lines = lines[1:]
    else:
        # Format baru: nomor soal menyatu di awal baris yang sama dengan
        # teks soal ("1. Sinonim: CERMAT adalah ...") — buang cuma bagian
        # nomornya, sisa teks di baris itu tetap dipakai.
        lines[0] = QNUM_PREFIX_RE.sub("", lines[0], count=1)
    body = "\n".join(lines).strip()
    if not body:
        return None

    # Coba format "(A) teks" dulu; kalau tidak ketemu cukup opsi, coba
    # format "A. teks". Satu soal hanya akan cocok salah satu (tidak pernah
    # campur dua format dalam PDF yang sama).
    matches = list(PAREN_OPTION_RE.finditer(body))
    if len(matches) < 2:
        matches = list(PERIOD_OPTION_RE.finditer(body))

    options = {}
    for m in matches:
        letter, text = m.group(1), m.group(2).strip().replace("\n", " ")
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            options[letter] = text

    if len(options) < 2:
        return None  # kemungkinan soal terpotong / lintas halaman / format tak dikenali

    first_option_pos = matches[0].start()
    question_text = body[:first_option_pos].strip()
    question_text = re.sub(r"\s+", " ", question_text).strip()

    multi_match = MULTI_RE.search(question_text)
    multi_answer = bool(multi_match)
    n_correct = int(multi_match.group(1)) if multi_match else 1

    return {
        "number": q_num,
        "question": question_text,
        "options": options,   # persis huruf yang terdeteksi, tidak dipaksa A-D
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
