import streamlit as st

from modules import auth_db, storage

st.title("📝 Kerjakan Soal (Siswa)")

siswa = auth_db.require_role("siswa")
profil = auth_db.get_siswa_profil(siswa["id"])
student_name = profil["nama_lengkap"] if profil else siswa["username"]

packages = storage.list_accessible_packages(siswa["id"])
if not packages:
    st.success("🎉 Semua paket soal yang diberikan gurumu sudah kamu kerjakan. "
               "Cek halaman 📊 Riwayat Nilai untuk melihat hasilnya (kalau sudah dinilai guru).")
    st.stop()

pkg_options = {f"{p['nama']} ({p['jumlah_soal']} soal)": p["id"] for p in packages}
selected_label = st.selectbox("Pilih paket soal", list(pkg_options.keys()))
pkg_id = pkg_options[selected_label]
st.caption(f"Mengerjakan sebagai **{student_name}**")

# Reset jawaban kalau paket soal berganti
if st.session_state.get("active_pkg_id") != pkg_id:
    st.session_state["active_pkg_id"] = pkg_id
    st.session_state["student_answers"] = {}
    st.session_state.pop("submission_done", None)

meta, question_images = storage.load_package(pkg_id)
questions = meta["questions"]

st.divider()
st.subheader(meta["name"])

if st.session_state.get("submission_done"):
    st.success("✅ Jawaban untuk paket ini sudah dikumpulkan. Gurumu akan menilainya dan hasilnya "
               "akan muncul di halaman 📊 Riwayat Nilai setelah dianalisis.")
    if st.button("➡️ Lanjut ke Paket Berikutnya", type="primary", use_container_width=True):
        st.session_state.pop("active_pkg_id", None)
        st.session_state.pop("submission_done", None)
        st.rerun()
    st.stop()

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
submit_clicked = st.button(
    "✅ Kumpulkan Jawaban", type="primary",
    disabled=not all_answered,
    use_container_width=True,
)
if not all_answered:
    st.caption("⚠️ Jawab semua soal terlebih dahulu untuk mengaktifkan tombol kumpulkan.")

if submit_clicked:
    storage.save_submission(siswa["id"], pkg_id, answers)
    st.session_state["submission_done"] = True
    st.rerun()
