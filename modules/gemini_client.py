"""
Wrapper tipis di atas SDK resmi `google-genai` untuk DUA kebutuhan AI di
aplikasi ini — dan hanya dua ini, supaya kuota API dipakai seperlunya:

1. `analyze_answers()` — tugas inti yang memang butuh penalaran AI:
   menentukan jawaban benar tiap soal + penjelasan singkat, dibandingkan
   dengan jawaban siswa. Hanya potongan gambar pendukung PER SOAL yang
   dikirim (bukan seluruh halaman PDF), supaya hemat token & kuota.

2. `parse_questions()` — FALLBACK opsional saja. Proses parsing soal dari
   PDF utamanya dilakukan oleh modules/text_parser.py (murni Python, tanpa
   AI sama sekali). Fungsi ini hanya dipakai kalau guru menekan tombol
   "Coba Parser AI (fallback)" karena parser bawaan gagal membaca PDF
   dengan layout yang tidak biasa.
"""

import json
import re

from google import genai
from google.genai import types
from PIL import Image

MODEL_NAME = "gemini-2.5-flash"
REQUEST_TIMEOUT_MS = 90_000   # 90 detik — supaya gagal jelas, bukan menggantung diam-diam
MAX_IMAGE_DIM = 768           # gambar diperkecil sebelum dikirim ke API: lebih cepat, lebih hemat token

_client = None


def configure(api_key: str):
    global _client
    _client = genai.Client(api_key=api_key)
    return _client


def _get_client():
    if _client is None:
        raise RuntimeError("Gemini client belum dikonfigurasi. Panggil configure(api_key) dulu.")
    return _client


def _for_api(img: Image.Image) -> Image.Image:
    """Perkecil gambar sebelum dikirim ke API. AI tidak perlu resolusi
    penuh untuk membaca tabel/grafik sederhana — mengirim gambar besar
    apa adanya cuma memperlambat request tanpa menambah akurasi."""
    w, h = img.size
    if max(w, h) <= MAX_IMAGE_DIM:
        return img
    scale = MAX_IMAGE_DIM / max(w, h)
    return img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)


def _extract_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text.strip())
    text = re.sub(r"```$", "", text.strip())
    text = text.strip()

    starts = [i for i in (text.find("["), text.find("{")) if i != -1]
    if starts:
        start = min(starts)
        end = max(text.rfind("]"), text.rfind("}"))
        if end != -1:
            text = text[start:end + 1]
    return json.loads(text)


# ---------------------------------------------------------------------------
# 1) Analisis jawaban (fungsi utama AI di aplikasi ini)
# ---------------------------------------------------------------------------

ANALYZE_PROMPT_HEADER = """
Kamu adalah guru ahli yang mengoreksi jawaban siswa untuk sebuah paket soal
ujian pilihan ganda. Berikut daftar soal beserta jawaban yang dipilih siswa
(format JSON). Beberapa soal punya gambar pendukung (tabel/grafik/diagram)
yang dilampirkan setelah blok JSON ini, masing-masing diberi label nomor
soalnya.

PENTING SOAL BAHASA: soal-soal ini bisa saja berasal dari mata pelajaran
Bahasa Arab, Bahasa Inggris, atau bahasa lain (teks soal & pilihan jawaban
mungkin ditulis dalam bahasa tsb — itu normal, JANGAN diterjemahkan atau
diubah). TAPI field "explanation" yang kamu tulis WAJIB selalu dalam Bahasa
Indonesia, apa pun bahasa soalnya, karena penjelasan ini untuk siswa
Indonesia yang sedang belajar. Field "correct_answer" tetap berupa huruf
opsi saja (mis. "B"), tidak perlu diterjemahkan.

{questions_json}

TUGAS KAMU untuk SETIAP soal:
1. Tentukan jawaban yang PALING BENAR (pakai gambar pendukung sebagai
   referensi jika soal itu punya gambar). Jika soal minta 2 jawaban benar
   (multi_answer=true, n_correct=2), berikan 2 huruf.
2. Berikan penjelasan SINGKAT (1-2 kalimat) DALAM BAHASA INDONESIA kenapa
   jawaban itu benar — meskipun teks soal aslinya berbahasa Arab, Inggris,
   atau bahasa lain.

Kembalikan HANYA JSON array (tanpa teks lain, tanpa markdown code fence)
dengan skema persis:

[
  {{
    "number": 1,
    "correct_answer": ["B"],
    "explanation": "penjelasan singkat kenapa B benar"
  }}
]
"""


ANALYZE_RESPONSE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "number": {"type": "integer"},
            "correct_answer": {"type": "array", "items": {"type": "string"}},
            "explanation": {"type": "string"},
        },
        "required": ["number", "correct_answer", "explanation"],
    },
}


def analyze_answers(questions_payload: list, question_images: dict, model_name: str = MODEL_NAME):
    """questions_payload: list of dict berisi number, question, options,
    multi_answer, n_correct, student_answer (list of letters).
    question_images: dict {number: PIL.Image} hanya untuk soal yang punya
    gambar pendukung — cuma ini yang dikirim ke API, bukan seluruh PDF.
    Mengembalikan list of dict: number, correct_answer (list), explanation."""
    client = _get_client()
    prompt = ANALYZE_PROMPT_HEADER.format(
        questions_json=json.dumps(questions_payload, ensure_ascii=False, indent=2)
    )
    contents = [prompt]
    for q in questions_payload:
        img = question_images.get(q["number"])
        if img is not None:
            contents.append(f"Gambar pendukung untuk soal nomor {q['number']}:")
            contents.append(_for_api(img))

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema=ANALYZE_RESPONSE_SCHEMA,
        max_output_tokens=8192,
        # Soal pilihan ganda + gambar sederhana tidak butuh "thinking" lama;
        # ini yang paling menentukan cepat/lambatnya respons.
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS),
    )

    try:
        resp = client.models.generate_content(model=model_name, contents=contents, config=config)
    except Exception as e:
        raise RuntimeError(
            "Permintaan ke Gemini gagal atau melebihi batas waktu (90 detik). "
            "Coba lagi — kalau masih gagal, periksa koneksi internet atau kuota API key kamu. "
            f"Detail teknis: {e}"
        ) from e

    if not resp.text:
        raise RuntimeError("Gemini tidak mengembalikan jawaban apa pun (respons kosong). Coba lagi.")

    try:
        data = _extract_json(resp.text)
    except (ValueError, json.JSONDecodeError) as e:
        raise RuntimeError(f"Respons AI tidak berupa JSON yang valid, coba lagi. Detail: {e}") from e

    if not isinstance(data, list):
        raise ValueError("Format hasil analisis AI tidak sesuai (bukan list).")
    return data


# ---------------------------------------------------------------------------
# 2) Fallback parser (opsional, hanya dipakai jika parser bawaan gagal)
# ---------------------------------------------------------------------------

PARSE_PROMPT = """
Kamu adalah asisten yang bertugas mengubah gambar halaman-halaman soal ujian
pilihan ganda menjadi data terstruktur JSON. Instruksi/petunjuk pada dokumen
ini umumnya berbahasa Indonesia, tapi TEKS SOAL & PILIHAN JAWABAN itu sendiri
bisa saja berbahasa Arab, Inggris, atau bahasa lain (mis. untuk mata
pelajaran Bahasa Arab / Bahasa Inggris) — SALIN APA ADANYA dalam bahasa
aslinya, JANGAN diterjemahkan ke Bahasa Indonesia.

ATURAN PENTING:
- Setiap soal punya nomor, kalimat soal (termasuk data pendukung seperti isi
  tabel, grafik, atau gambar yang relevan — tuliskan ulang datanya dalam
  bentuk teks/markdown di dalam field "question" agar soal tetap bisa
  dipahami tanpa melihat gambar aslinya lagi), dan pilihan jawaban (A)-(D).
- Jika soal meminta memilih LEBIH DARI SATU jawaban benar (biasanya ada teks
  seperti "Pilihlah 2 Jawaban Benar!"), set "multi_answer": true dan
  "n_correct": jumlah jawaban benar yang diminta. Jika soal biasa (1 jawaban
  benar), set "multi_answer": false dan "n_correct": 1.
- Abaikan header/footer dokumen (judul ujian, logo, dsb) — itu bukan soal.
- Urutkan hasil berdasarkan nomor soal.
- JANGAN mencoba menjawab soal di tahap ini. Kembalikan HANYA JSON array
  (tanpa teks lain, tanpa markdown code fence), dengan skema persis:

[
  {
    "number": 1,
    "question": "teks lengkap soal, termasuk data tabel/grafik pendukung",
    "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
    "multi_answer": false,
    "n_correct": 1
  }
]
"""


PARSE_RESPONSE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "number": {"type": "integer"},
            "question": {"type": "string"},
            "options": {
                "type": "object",
                "properties": {
                    "A": {"type": "string"}, "B": {"type": "string"},
                    "C": {"type": "string"}, "D": {"type": "string"},
                },
                "required": ["A", "B", "C", "D"],
            },
            "multi_answer": {"type": "boolean"},
            "n_correct": {"type": "integer"},
        },
        "required": ["number", "question", "options", "multi_answer", "n_correct"],
    },
}


def parse_questions(page_images: list, model_name: str = MODEL_NAME):
    """Fallback: kirim seluruh gambar halaman PDF ke Gemini untuk dipecah
    jadi soal-soal terstruktur. Dipakai hanya jika parser bawaan
    (text_parser.parse_pdf) gagal/kurang baik untuk PDF tertentu."""
    client = _get_client()
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema=PARSE_RESPONSE_SCHEMA,
        max_output_tokens=8192,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS),
    )
    try:
        resp = client.models.generate_content(
            model=model_name,
            contents=[PARSE_PROMPT, *[_for_api(im) for im in page_images]],
            config=config,
        )
    except Exception as e:
        raise RuntimeError(
            "Permintaan ke Gemini gagal atau melebihi batas waktu. Coba lagi. "
            f"Detail teknis: {e}"
        ) from e

    if not resp.text:
        raise RuntimeError("Gemini tidak mengembalikan jawaban apa pun (respons kosong). Coba lagi.")

    data = _extract_json(resp.text)
    if not isinstance(data, list):
        raise ValueError("Format hasil parsing AI tidak sesuai (bukan list).")
    return data
