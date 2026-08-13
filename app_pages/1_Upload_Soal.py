import streamlit as st

from modules import auth_db, gemini_client, pdf_parser, storage, text_parser
from modules.auth import get_gemini_api_key

st.title("📤 Upload Soal (Guru)")

guru = auth_db.require_role("guru")
api_key = get_gemini_api_key()

pkg_name = st.text_input(
    "Nama paket soal", value=st.session_state.get("pkg_name", ""),
    placeholder="Contoh: Latihan IPA - SNPDB 2023", key="pkg_name",
)
uploaded_pdf = st.file_uploader("Unggah file PDF soal pilihan ganda", type=["pdf"])

if uploaded_pdf is not None:
    pdf_bytes_key = f"pdf_bytes_{uploaded_pdf.name}_{uploaded_pdf.size}"
    if st.session_state.get("pdf_bytes_key") != pdf_bytes_key:
        st.session_state["pdf_bytes_key"] = pdf_bytes_key
        st.session_state["pdf_bytes"] = uploaded_pdf.getvalue()
        st.session_state.pop("parsed_questions", None)
        # Bantu isi nama paket otomatis dari nama file kalau masih kosong,
        # supaya guru tidak lupa mengisinya sebelum menyimpan nanti.
        if not st.session_state.get("pkg_name"):
            st.session_state["pkg_name"] = uploaded_pdf.name.rsplit(".", 1)[0]
            st.rerun()

col1, col2 = st.columns(2)
with col1:
    free_parse_clicked = st.button(
        "🧩 Proses PDF (Parser Bawaan — Gratis, Tanpa AI)", type="primary",
        disabled=uploaded_pdf is None,
        help="Membaca teks & gambar PDF langsung dengan Python. Tidak memakai kuota API sama sekali.",
    )
with col2:
    ai_parse_clicked = st.button(
        "🤖 Coba Parser AI (fallback, pakai kuota)", disabled=not (uploaded_pdf and api_key),
        help="Gunakan hanya jika parser bawaan gagal membaca soal dengan benar (mis. layout PDF tidak biasa).",
    )

if free_parse_clicked:
    with st.spinner("Membaca PDF dengan parser bawaan (tanpa AI)..."):
        try:
            questions = text_parser.parse_pdf(st.session_state["pdf_bytes"])
        except Exception as e:
            st.error(f"Gagal membaca PDF: {e}")
            questions = []
    if questions:
        st.session_state["parsed_questions"] = questions
        st.success(f"Berhasil membaca {len(questions)} soal tanpa memakai kuota AI sama sekali. "
                   f"Silakan periksa di bawah sebelum menyimpan.")
    else:
        st.warning("Parser bawaan tidak menemukan soal yang cocok pada PDF ini. "
                   "Coba tombol 'Parser AI (fallback)' di sebelah kanan, atau periksa format PDF-nya.")

if ai_parse_clicked:
    with st.spinner("Mengubah PDF menjadi gambar halaman..."):
        page_images = pdf_parser.pdf_to_images(st.session_state["pdf_bytes"])
    with st.spinner("AI sedang membaca & menyusun soal (bisa memakan waktu 1-2 menit)..."):
        try:
            gemini_client.configure(api_key)
            ai_questions = gemini_client.parse_questions(page_images)
            # Fallback AI tidak menghasilkan potongan gambar presisi seperti
            # parser bawaan, jadi field "image" dikosongkan (guru bisa
            # menambahkan gambar pendukung secara manual bila perlu).
            for q in ai_questions:
                q["image"] = None
            questions = ai_questions
        except Exception as e:
            st.error(f"Gagal memproses PDF dengan AI: {e}")
            questions = None
    if questions:
        st.session_state["parsed_questions"] = questions
        st.success(f"AI berhasil mengekstrak {len(questions)} soal. Silakan periksa di bawah sebelum menyimpan.")

if "parsed_questions" in st.session_state:
    st.divider()
    st.subheader("Tinjau & Sunting Soal")
    st.caption("Periksa hasil ekstraksi. Kamu bisa mengubah teks soal / opsi jika ada yang kurang tepat "
               "sebelum disimpan.")

    questions = st.session_state["parsed_questions"]
    edited_questions = []
    for q in questions:
        badge = " (2 jawaban benar)" if q.get("multi_answer") else ""
        img = q.get("image")
        with st.expander(f"Soal {q['number']}{badge}" + (" 🖼️" if img is not None else "")):
            left, right = st.columns([3, 2])
            with left:
                q_text = st.text_area("Teks soal", value=q["question"], key=f"qtext_{q['number']}", height=100)
                new_options = {}
                for letter in q["options"].keys():
                    new_options[letter] = st.text_input(
                        f"Opsi {letter}", value=q["options"].get(letter, ""), key=f"opt_{letter}_{q['number']}"
                    )
                multi = st.checkbox("Soal ini butuh 2 jawaban benar", value=q.get("multi_answer", False),
                                     key=f"multi_{q['number']}")
            with right:
                if img is not None:
                    st.image(img, caption="Gambar pendukung terdeteksi", use_container_width=True)
                else:
                    st.caption("Tidak ada gambar pendukung terdeteksi untuk soal ini.")

            edited_questions.append({
                "number": q["number"],
                "question": q_text,
                "options": new_options,
                "multi_answer": multi,
                "n_correct": 2 if multi else 1,
                "image": img,
            })

    st.divider()
    name_ok = bool(pkg_name.strip())
    save_clicked = st.button("💾 Simpan Paket Soal", type="primary", disabled=not name_ok)
    if not name_ok:
        st.caption("⚠️ Isi \"Nama paket soal\" di bagian atas halaman dulu supaya tombol ini aktif.")
    if save_clicked:
        pkg_id = storage.save_package(pkg_name.strip(), edited_questions, guru["id"])
        st.success(f"Paket soal '{pkg_name.strip()}' tersimpan (ID: {pkg_id}). "
                   f"Buka halaman 👩‍🏫 Kelola Siswa untuk memberikan akses paket ini ke siswa tertentu.")
        del st.session_state["parsed_questions"]

st.divider()
st.subheader("📦 Paket Soal Tersimpan")
packages = storage.list_packages_by_guru(guru["id"])
if not packages:
    st.caption("Belum ada paket soal.")
else:
    for pkg in packages:
        c1, c2, c3 = st.columns([4, 2, 1])
        c1.write(f"**{pkg['nama']}** — {pkg['jumlah_soal']} soal")
        c2.caption(str(pkg["created_at"]))
        if c3.button("Hapus", key=f"del_{pkg['id']}"):
            storage.delete_package(pkg["id"])
            st.rerun()
