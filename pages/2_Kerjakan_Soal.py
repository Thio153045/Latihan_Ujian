import streamlit as st

from modules import auth_db, gemini_client, pdf_report, storage
from modules.auth import get_gemini_api_key

st.title("📝 Kerjakan Soal (Siswa)")

siswa = auth_db.current_user()
profil = auth_db.get_siswa_profil(siswa["id"])
api_key = get_gemini_api_key()

packages = storage.list_accessible_packages(siswa["id"])
if not packages:
    st.warning("Belum ada paket soal yang diberikan gurumu. Hubungi gurumu untuk mendapatkan akses.")
    st.stop()

pkg_options = {f"{p['nama']} ({p['jumlah_soal']} soal)": p["id"] for p in packages}
selected_label = st.selectbox("Pilih paket soal", list(pkg_options.keys()))
pkg_id = pkg_options[selected_label]
student_name = profil["nama_lengkap"] if profil else siswa["username"]
st.caption(f"Mengerjakan sebagai **{student_name}**")

# Reset jawaban kalau paket soal berganti
if st.session_state.get("active_pkg_id") != pkg_id:
    st.session_state["active_pkg_id"] = pkg_id
    st.session_state["student_answers"] = {}
    st.session_state.pop("analysis_results", None)

meta, question_images = storage.load_package(pkg_id)
questions = meta["questions"]

st.divider()
st.subheader(meta["name"])

answers = st.session_state["student_answers"]
total_q = len(questions)

for q in questions:
    with st.container(border=True):
        badge = "🔵🔵 Pilih 2 jawaban benar" if q.get("multi_answer") else ""
        header_cols = st.columns([5, 2])
        header_cols[0].markdown(f"**Soal {q['number']}**")
        if badge:
            header_cols[1].caption(badge)

        st.markdown(q["question"])

        if q["number"] in question_images:
            st.image(question_images[q["number"]], caption="Gambar/tabel pendukung soal",
                      use_container_width=True)

        opt_labels = [f"{letter}. {text}" for letter, text in q["options"].items()]

        if q.get("multi_answer"):
            n_correct = q.get("n_correct", 2)
            chosen = st.multiselect(
                f"Pilih {n_correct} jawaban benar",
                options=opt_labels,
                default=[],
                max_selections=n_correct,
                key=f"ans_{q['number']}",
            )
            answers[q["number"]] = [c.split(".")[0] for c in chosen]
        else:
            choice = st.radio(
                "Pilih jawaban", options=opt_labels, index=None, key=f"ans_{q['number']}"
            )
            answers[q["number"]] = [choice.split(".")[0]] if choice else []

st.session_state["student_answers"] = answers

answered_q = sum(1 for q in questions if len(answers.get(q["number"], [])) > 0)
st.progress(answered_q / total_q if total_q else 0, text=f"{answered_q}/{total_q} soal terjawab")

all_answered = answered_q == total_q
analyze_clicked = st.button(
    "🤖 Analisa dengan AI", type="primary",
    disabled=not (all_answered and api_key),
    use_container_width=True,
)
if not api_key:
    st.caption("⚠️ Gemini API Key belum dikonfigurasi guru/admin.")
elif not all_answered:
    st.caption("⚠️ Jawab semua soal terlebih dahulu untuk mengaktifkan tombol analisa.")

if analyze_clicked:
    payload = [
        {
            "number": q["number"],
            "question": q["question"],
            "options": q["options"],
            "multi_answer": q.get("multi_answer", False),
            "n_correct": q.get("n_correct", 1),
            "student_answer": answers.get(q["number"], []),
        }
        for q in questions
    ]
    with st.spinner("AI sedang menentukan jawaban benar & menyusun penjelasan... "
                 "(kalau server Gemini sedang sibuk, ini otomatis dicoba ulang beberapa kali)"):
        try:
            gemini_client.configure(api_key)
            ai_result = gemini_client.analyze_answers(payload, question_images)
        except Exception as e:
            st.error(f"Gagal menganalisis jawaban: {e}")
            ai_result = None

    if ai_result:
        ai_by_number = {r["number"]: r for r in ai_result}
        results = []
        score = 0
        for q in questions:
            n = q["number"]
            correct = set(ai_by_number.get(n, {}).get("correct_answer", []))
            student = set(answers.get(n, []))
            is_correct = student == correct and len(correct) > 0
            if is_correct:
                score += 1
            results.append({
                "number": n,
                "question": q["question"],
                "options": q["options"],
                "correct_answer": list(correct),
                "student_answer": list(student),
                "is_correct": is_correct,
                "explanation": ai_by_number.get(n, {}).get("explanation", "-"),
            })
        st.session_state["analysis_results"] = results
        st.session_state["analysis_score"] = score
        # Simpan ke riwayat nilai siswa (tabel hasil_ujian + jawaban_detail)
        storage.save_hasil_ujian(siswa["id"], pkg_id, score, total_q, results)

if "analysis_results" in st.session_state:
    results = st.session_state["analysis_results"]
    score = st.session_state["analysis_score"]
    st.divider()

    pct = round(100 * score / total_q, 1) if total_q else 0
    st.header(f"📊 Hasil: {score} / {total_q} Benar ({pct}%)")
    st.caption("Hasil ini otomatis tersimpan di riwayat nilaimu.")

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

    pdf_buffer = pdf_report.generate_result_pdf(meta["name"], student_name, results, score, total_q, question_images)
    st.download_button(
        "⬇️ Unduh Hasil (PDF)",
        data=pdf_buffer,
        file_name=f"hasil_{meta['name'].replace(' ', '_')}_{student_name.replace(' ', '_')}.pdf",
        mime="application/pdf",
        type="primary",
        use_container_width=True,
    )
