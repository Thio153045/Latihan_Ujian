"""Membuat PDF hasil latihan soal (soal, jawaban siswa, jawaban benar versi
AI, penjelasan singkat, dan skor akhir) untuk diunduh siswa sebagai bahan
belajar ulang. Soal yang punya tabel/grafik/gambar pendukung ikut
menyertakan potongan gambarnya di dalam PDF."""

import io

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (HRFlowable, Image, Paragraph,
                                 SimpleDocTemplate, Spacer)

MAX_IMG_WIDTH = 12 * cm


def _fitted_image(pil_img: PILImage.Image) -> Image:
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    buf.seek(0)
    w, h = pil_img.size
    scale = min(MAX_IMG_WIDTH / w, 1.0)
    return Image(buf, width=w * scale, height=h * scale)


def generate_result_pdf(package_name: str, student_name: str, results: list,
                         score: int, total: int, question_images=None) -> io.BytesIO:
    question_images = question_images or {}
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=2 * cm, bottomMargin=2 * cm,
        leftMargin=2 * cm, rightMargin=2 * cm,
    )
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle("TitleX", parent=styles["Title"], fontSize=16, spaceAfter=2)
    q_style = ParagraphStyle("Q", parent=styles["Normal"], fontName="Helvetica-Bold",
                              fontSize=11, spaceBefore=10, spaceAfter=4)
    opt_style = ParagraphStyle("Opt", parent=styles["Normal"], fontSize=10, leftIndent=10)
    opt_correct_style = ParagraphStyle("OptCorrect", parent=opt_style,
                                        textColor=colors.HexColor("#1a7f37"),
                                        fontName="Helvetica-Bold")
    ans_style = ParagraphStyle("Ans", parent=styles["Normal"], fontSize=10, spaceBefore=4)
    ans_correct_style = ParagraphStyle("AnsCorrect", parent=ans_style,
                                        textColor=colors.HexColor("#1a7f37"))
    ans_wrong_style = ParagraphStyle("AnsWrong", parent=ans_style,
                                      textColor=colors.HexColor("#c0392b"))
    exp_style = ParagraphStyle("Exp", parent=styles["Normal"], fontSize=9.5,
                                textColor=colors.HexColor("#555555"), leftIndent=10,
                                spaceAfter=4)

    story.append(Paragraph(f"Hasil Latihan Soal — {package_name}", title_style))
    story.append(Paragraph(f"Nama Siswa: {student_name}", styles["Normal"]))
    pct = round(100 * score / total, 1) if total else 0
    story.append(Paragraph(
        f"Skor Akhir: <b>{score} / {total}</b> ({pct}%)",
        ParagraphStyle("Score", parent=styles["Heading2"], spaceBefore=6, spaceAfter=10)
    ))
    story.append(HRFlowable(width="100%", color=colors.grey))

    for r in results:
        story.append(Paragraph(f"{r['number']}. {r['question']}", q_style))

        img = question_images.get(r["number"])
        if img is not None:
            story.append(Spacer(1, 4))
            story.append(_fitted_image(img))
            story.append(Spacer(1, 4))

        correct_set = set(r["correct_answer"])
        for letter, text in r["options"].items():
            style = opt_correct_style if letter in correct_set else opt_style
            suffix = "  ✓ Jawaban Benar" if letter in correct_set else ""
            story.append(Paragraph(f"({letter}) {text}{suffix}", style))

        siswa = ", ".join(r["student_answer"]) if r["student_answer"] else "(tidak dijawab)"
        status = "✓ BENAR" if r["is_correct"] else "✗ SALAH"
        status_style = ans_correct_style if r["is_correct"] else ans_wrong_style
        story.append(Paragraph(f"Jawaban Siswa: <b>{siswa}</b> — <b>{status}</b>", status_style))
        story.append(Paragraph(f"<i>Penjelasan AI: {r['explanation']}</i>", exp_style))
        story.append(HRFlowable(width="100%", color=colors.lightgrey))

    doc.build(story)
    buffer.seek(0)
    return buffer
