import streamlit as st

from modules import auth_db, pdf_report, storage

st.title("📊 Riwayat Nilai")

siswa = auth_db.current_user()
profil = auth_db.get_siswa_profil(siswa["id"])
student_name = profil["nama_lengkap"] if profil else siswa["username"]

riwayat = storage.list_riwayat_siswa(siswa["id"])

if not riwayat:
    st.info("Belum ada riwayat pengerjaan soal. Kerjakan soal dulu di halaman 📝 Kerjakan Soal.")
    st.stop()

for r in riwayat:
    with st.container(border=True):
        c1, c2 = st.columns([4, 2])
        with c1:
            st.markdown(f"**{r['paket_nama']}**")
            st.caption(str(r["dikerjakan_at"]))
        with c2:
            if r["status"] == "menunggu":
                st.info("⏳ Menunggu dinilai guru")
            else:
                pct = round(100 * r["skor"] / r["total_soal"], 1) if r["total_soal"] else 0
                st.metric("Skor", f"{r['skor']} / {r['total_soal']}", f"{pct}%")

        if r["status"] == "selesai" and st.button("Lihat detail & unduh PDF", key=f"detail_{r['id']}"):
            st.session_state["riwayat_detail_id"] = r["id"]
            st.rerun()

if "riwayat_detail_id" in st.session_state:
    header, results, question_images = storage.load_hasil_detail(st.session_state["riwayat_detail_id"])
    if header:
        st.divider()
        st.subheader(f"Detail: {header['paket_nama']}")
        for r in results:
            icon = "✅" if r["is_correct"] else "❌"
            with st.container(border=True):
                st.markdown(f"{icon} **{r['number']}. {r['question']}**")
                if r["number"] in question_images:
                    st.image(question_images[r["number"]], caption="Gambar/tabel pendukung soal",
                              use_container_width=True)
                for letter, text in r["options"].items():
                    if letter in r["correct_answer"]:
                        st.markdown(f"- **{letter}. {text}**  ✓ jawaban benar")
                    else:
                        st.markdown(f"- {letter}. {text}")
                siswa_jwb = ", ".join(r["student_answer"]) if r["student_answer"] else "(tidak dijawab)"
                st.markdown(f"Jawaban kamu: **{siswa_jwb}**")
                st.caption(f"💡 {r['explanation']}")

        pdf_buffer = pdf_report.generate_result_pdf(
            header["paket_nama"], student_name, results, header["skor"], header["total_soal"], question_images
        )
        st.download_button(
            "⬇️ Unduh Hasil (PDF)", data=pdf_buffer,
            file_name=f"hasil_{header['paket_nama'].replace(' ', '_')}_{student_name.replace(' ', '_')}.pdf",
            mime="application/pdf", type="primary", use_container_width=True,
        )
