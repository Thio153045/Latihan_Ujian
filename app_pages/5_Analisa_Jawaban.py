import streamlit as st

from modules import auth_db, excel_report, gemini_client, pdf_report, storage
from modules.auth import get_gemini_api_key

st.title("🧮 Analisa Jawaban Siswa")

guru = auth_db.require_role("guru")
api_key = get_gemini_api_key()

siswa_list = auth_db.list_siswa_by_guru(guru["id"])
paket_list = storage.list_packages_by_guru(guru["id"])
siswa_by_name = {s["nama_lengkap"]: s["user_id"] for s in siswa_list}
paket_by_name = {p["nama"]: p["id"] for p in paket_list}


def _pdf_download(hasil_id: int, student_name: str, key_suffix: str):
    header, results, qimgs = storage.load_hasil_detail(hasil_id)
    if not header:
        st.error("Data tidak ditemukan.")
        return
    buf = pdf_report.generate_result_pdf(
        header["paket_nama"], student_name, results, header["skor"], header["total_soal"], qimgs
    )
    st.download_button(
        "⬇️ Unduh PDF", data=buf,
        file_name=f"hasil_{header['paket_nama'].replace(' ', '_')}_{student_name.replace(' ', '_')}.pdf",
        mime="application/pdf", key=f"pdf_{key_suffix}",
    )


# ---------------------------------------------------------------------------
# 1) Menunggu dianalisis
# ---------------------------------------------------------------------------
st.subheader("⏳ Menunggu Dianalisis")

c1, c2 = st.columns(2)
with c1:
    filter_siswa_1 = st.selectbox("Filter siswa", ["Semua Siswa"] + list(siswa_by_name.keys()), key="f_siswa_pending")
with c2:
    filter_paket_1 = st.selectbox("Filter paket", ["Semua Paket"] + list(paket_by_name.keys()), key="f_paket_pending")

pending = storage.list_pending_submissions(
    guru["id"],
    siswa_id=siswa_by_name.get(filter_siswa_1),
    paket_id=paket_by_name.get(filter_paket_1),
)

if not pending:
    st.caption("Tidak ada jawaban yang menunggu dianalisis.")
else:
    st.caption(f"{len(pending)} submisi menunggu. Pilih yang ingin dianalisis:")
    selected_ids = []
    for p in pending:
        label = f"{p['nama_lengkap']} ({p['kelas']}) — {p['paket_nama']} · dikumpulkan {p['dikerjakan_at']}"
        checked = st.checkbox(label, key=f"pending_{p['id']}")
        if checked:
            selected_ids.append(p["id"])

    analyze_clicked = st.button(
        f"🤖 Analisa {len(selected_ids)} Terpilih dengan AI", type="primary",
        disabled=not (selected_ids and api_key),
    )
    if not api_key:
        st.caption("⚠️ Gemini API Key belum dikonfigurasi.")

    if analyze_clicked:
        gemini_client.configure(api_key)
        just_analyzed = []
        progress = st.progress(0, text="Memulai analisa...")
        for i, hasil_id in enumerate(selected_ids):
            row = next(p for p in pending if p["id"] == hasil_id)
            progress.progress(
                i / len(selected_ids),
                text=f"Menganalisis {row['nama_lengkap']} — {row['paket_nama']}...",
            )
            try:
                payload, qimgs = storage.get_submission_for_analysis(hasil_id)
                ai_result = gemini_client.analyze_answers(payload, qimgs)
                score = storage.apply_analysis_result(hasil_id, guru["id"], ai_result)
                just_analyzed.append({**row, "skor": score})
            except Exception as e:
                st.error(f"Gagal menganalisis {row['nama_lengkap']} — {row['paket_nama']}: {e}")
        progress.progress(1.0, text="Selesai.")

        if just_analyzed:
            st.success(f"Berhasil menganalisis {len(just_analyzed)} submisi.")
            st.session_state["just_analyzed"] = just_analyzed
            st.rerun()

if "just_analyzed" in st.session_state:
    just_analyzed = st.session_state["just_analyzed"]
    st.divider()
    st.markdown("**Hasil analisa barusan:**")
    for r in just_analyzed:
        pct = round(100 * r["skor"] / r["total_soal"], 1) if r["total_soal"] else 0
        c1, c2, c3 = st.columns([3, 2, 2])
        c1.write(f"{r['nama_lengkap']} — {r['paket_nama']}")
        c2.write(f"Skor: {r['skor']}/{r['total_soal']} ({pct}%)")
        with c3:
            _pdf_download(r["id"], r["nama_lengkap"], f"just_{r['id']}")

    if len(just_analyzed) > 1:
        excel_buf = excel_report.generate_recap_excel(just_analyzed)
        st.download_button(
            "📊 Unduh Rekap Excel (Semua yang Baru Dianalisis)", data=excel_buf,
            file_name="rekap_nilai.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )
    if st.button("Tutup ringkasan ini"):
        del st.session_state["just_analyzed"]
        st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# 2) Riwayat nilai (sudah dianalisis) — bisa unduh ulang PDF / Excel rekap
# ---------------------------------------------------------------------------
st.subheader("📚 Riwayat Nilai (Sudah Dianalisis)")

c1, c2 = st.columns(2)
with c1:
    filter_siswa_2 = st.selectbox("Filter siswa", ["Semua Siswa"] + list(siswa_by_name.keys()), key="f_siswa_done")
with c2:
    filter_paket_2 = st.selectbox("Filter paket", ["Semua Paket"] + list(paket_by_name.keys()), key="f_paket_done")

completed = storage.list_completed_submissions(
    guru["id"],
    siswa_id=siswa_by_name.get(filter_siswa_2),
    paket_id=paket_by_name.get(filter_paket_2),
)

if not completed:
    st.caption("Belum ada nilai yang sudah dianalisis untuk filter ini.")
else:
    selected_for_excel = []
    for r in completed:
        pct = round(100 * r["skor"] / r["total_soal"], 1) if r["total_soal"] else 0
        c1, c2, c3, c4 = st.columns([0.5, 2.5, 2, 2])
        with c1:
            pick = st.checkbox("", key=f"done_pick_{r['id']}", label_visibility="collapsed")
            if pick:
                selected_for_excel.append(r)
        c2.write(f"{r['nama_lengkap']} — {r['paket_nama']}")
        c3.write(f"Skor: {r['skor']}/{r['total_soal']} ({pct}%)")
        with c4:
            _pdf_download(r["id"], r["nama_lengkap"], f"done_{r['id']}")

    if len(selected_for_excel) > 1:
        excel_buf = excel_report.generate_recap_excel(selected_for_excel)
        st.download_button(
            f"📊 Unduh Rekap Excel ({len(selected_for_excel)} Siswa Terpilih)", data=excel_buf,
            file_name="rekap_nilai.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )
    elif len(completed) > 1:
        st.caption("Centang minimal 2 baris untuk mengunduh rekap Excel gabungan.")
