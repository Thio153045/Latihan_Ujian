import datetime

import streamlit as st

from modules import auth_db, storage

st.title("👩‍🏫 Kelola Siswa")

guru = auth_db.current_user()


def hitung_usia(tanggal_lahir) -> int:
    today = datetime.date.today()
    if isinstance(tanggal_lahir, str):
        tanggal_lahir = datetime.date.fromisoformat(tanggal_lahir)
    return today.year - tanggal_lahir.year - (
        (today.month, today.day) < (tanggal_lahir.month, tanggal_lahir.day)
    )


# ---------------------------------------------------------------------------
# 1) Buat akun siswa baru
# ---------------------------------------------------------------------------
with st.expander("➕ Buat Akun Siswa Baru", expanded=False):
    with st.form("form_siswa_baru", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            username = st.text_input("Username")
            password = st.text_input("Password awal", type="password",
                                      help="Siswa akan diminta ganti password saat login pertama kali.")
            nama_lengkap = st.text_input("Nama lengkap")
            tanggal_lahir = st.date_input(
                "Tanggal lahir", value=datetime.date(2012, 1, 1),
                min_value=datetime.date(1990, 1, 1), max_value=datetime.date.today(),
            )
        with c2:
            jenis_kelamin = st.radio("Jenis kelamin", options=["L", "P"],
                                      format_func=lambda x: "Laki-laki" if x == "L" else "Perempuan")
            kelas = st.text_input("Kelas", placeholder="Contoh: 6A")
            nama_sekolah = st.text_input("Nama sekolah")

        submitted = st.form_submit_button("Buat Akun Siswa", type="primary")

    if submitted:
        errors = []
        if not username.strip():
            errors.append("Username wajib diisi.")
        elif auth_db.username_exists(username.strip()):
            errors.append(f"Username '{username.strip()}' sudah dipakai.")
        if len(password) < 6:
            errors.append("Password awal minimal 6 karakter.")
        if not nama_lengkap.strip():
            errors.append("Nama lengkap wajib diisi.")
        if not kelas.strip():
            errors.append("Kelas wajib diisi.")
        if not nama_sekolah.strip():
            errors.append("Nama sekolah wajib diisi.")

        if errors:
            for e in errors:
                st.error(e)
        else:
            auth_db.create_siswa(
                username.strip(), password, guru["id"], nama_lengkap.strip(),
                tanggal_lahir.isoformat(), jenis_kelamin, kelas.strip(), nama_sekolah.strip(),
            )
            st.success(f"Akun siswa '{username.strip()}' berhasil dibuat. "
                       f"Sampaikan username & password awal ini ke siswa secara langsung.")
            st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# 2) Daftar siswa + kontrol akses paket soal
# ---------------------------------------------------------------------------
st.subheader("📋 Daftar Siswa & Akses Paket Soal")

siswa_list = auth_db.list_siswa_by_guru(guru["id"])
paket_list = storage.list_packages_by_guru(guru["id"])

if not siswa_list:
    st.caption("Belum ada siswa yang dibuat.")
elif not paket_list:
    st.caption("Buat paket soal dulu di halaman 📤 Upload Soal sebelum mengatur akses.")
else:
    access_map = storage.get_access_map(guru["id"])  # {siswa_user_id: {paket_id, ...}}
    paket_by_id = {p["id"]: p["nama"] for p in paket_list}

    # --- opsi cepat: berikan akses ke satu kelas sekaligus ---
    with st.expander("⚡ Berikan Akses ke Satu Kelas Sekaligus"):
        kelas_options = sorted({s["kelas"] for s in siswa_list})
        c1, c2, c3 = st.columns([2, 2, 1])
        with c1:
            target_kelas = st.selectbox("Kelas", kelas_options, key="bulk_kelas")
        with c2:
            target_paket_label = st.selectbox(
                "Paket soal", list(paket_by_id.values()), key="bulk_paket"
            )
        target_paket_id = next(pid for pid, nama in paket_by_id.items() if nama == target_paket_label)
        with c3:
            st.write("")
            st.write("")
            if st.button("Berikan Akses", use_container_width=True):
                for s in siswa_list:
                    if s["kelas"] == target_kelas:
                        storage.grant_access(s["user_id"], target_paket_id, guru["id"])
                st.success(f"Akses paket '{target_paket_label}' diberikan ke semua siswa kelas {target_kelas}.")
                st.rerun()

    st.write("")
    for s in siswa_list:
        usia = hitung_usia(s["tanggal_lahir"])
        jk_label = "Laki-laki" if s["jenis_kelamin"] == "L" else "Perempuan"
        with st.expander(f"{s['nama_lengkap']} — {s['kelas']} ({s['username']})"):
            st.caption(f"{jk_label} · {usia} tahun · {s['nama_sekolah']}")
            current_access = access_map.get(s["user_id"], set())
            selected_names = st.multiselect(
                "Paket soal yang boleh diakses",
                options=list(paket_by_id.values()),
                default=[paket_by_id[pid] for pid in current_access if pid in paket_by_id],
                key=f"access_{s['user_id']}",
            )
            selected_ids = {pid for pid, nama in paket_by_id.items() if nama in selected_names}

            if selected_ids != current_access:
                if st.button("💾 Simpan Akses", key=f"save_access_{s['user_id']}"):
                    for pid in selected_ids - current_access:
                        storage.grant_access(s["user_id"], pid, guru["id"])
                    for pid in current_access - selected_ids:
                        storage.revoke_access(s["user_id"], pid)
                    st.success("Akses diperbarui.")
                    st.rerun()
