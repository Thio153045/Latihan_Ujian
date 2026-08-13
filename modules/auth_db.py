"""Autentikasi & manajemen sesi pengguna (guru/siswa) via database MySQL.

Sesi login disimpan di st.session_state — bertahan selama tab browser masih
terhubung ke sesi Streamlit yang sama (termasuk saat berpindah halaman di
dalam aplikasi), tapi akan hilang kalau tab di-refresh penuh (F5) atau
ditutup. Ini keterbatasan yang disengaja untuk versi ini supaya scope tetap
terkendali; bisa ditingkatkan nanti pakai session cookie kalau memang
dibutuhkan (lihat catatan di README).
"""

import bcrypt
import streamlit as st

from modules import db

SESSION_KEY = "auth_user"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def authenticate(username: str, password: str):
    row = db.fetch_one("SELECT * FROM users WHERE username = :u", {"u": username})
    if row and verify_password(password, row["password_hash"]):
        return row
    return None


def login(username: str, password: str) -> bool:
    user = authenticate(username, password)
    if user is None:
        return False
    st.session_state[SESSION_KEY] = {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "must_change_password": bool(user["must_change_password"]),
    }
    return True


def logout():
    st.session_state.pop(SESSION_KEY, None)


def is_logged_in() -> bool:
    return SESSION_KEY in st.session_state


def current_user():
    return st.session_state.get(SESSION_KEY)

def require_role(expected_role: str):
    """Guard yang WAJIB dipanggil di baris pertama tiap halaman (guru atau
    siswa). Kalau sesi login sudah tidak ada — misalnya karena aplikasi
    baru bangun dari 'tidur' di Streamlit Cloud dan session_state server
    sempat kosong sementara browser masih menampilkan halaman lama — atau
    kalau role-nya tidak cocok (mis. siswa mencoba buka halaman guru lewat
    URL langsung), halaman dihentikan dengan pesan yang jelas alih-alih
    crash dengan error mentah seperti "NoneType is not subscriptable"."""
    if not is_logged_in():
        st.warning("⚠️ Sesi login sudah berakhir (mungkin karena aplikasi baru bangun dari "
                    "'tidur'). Silakan muat ulang halaman ini (F5) untuk login kembali.")
        st.stop()
    user = current_user()
    if user["role"] != expected_role:
        st.error("Kamu tidak punya akses ke halaman ini.")
        st.stop()
    return user

def change_password(user_id: int, new_password: str):
    db.execute(
        "UPDATE users SET password_hash = :p, must_change_password = 0 WHERE id = :id",
        {"p": hash_password(new_password), "id": user_id},
    )
    if is_logged_in() and current_user()["id"] == user_id:
        st.session_state[SESSION_KEY]["must_change_password"] = False


def username_exists(username: str) -> bool:
    return db.fetch_one("SELECT id FROM users WHERE username = :u", {"u": username}) is not None


def create_guru(username: str, password: str) -> int:
    """Dipakai lewat script setup awal (scripts/create_guru.py), BUKAN dari
    UI publik — supaya tidak sembarang orang bisa mendaftar sebagai guru."""
    res = db.execute(
        "INSERT INTO users (username, password_hash, role) VALUES (:u, :p, 'guru')",
        {"u": username, "p": hash_password(password)},
    )
    return res.lastrowid


def create_siswa(username: str, password: str, created_by: int, nama_lengkap: str,
                  tanggal_lahir, jenis_kelamin: str, kelas: str, nama_sekolah: str) -> int:
    """Dipanggil guru dari halaman Kelola Siswa. must_change_password=1
    supaya siswa wajib ganti password bawaan saat login pertama kali."""
    res = db.execute(
        "INSERT INTO users (username, password_hash, role, must_change_password, created_by) "
        "VALUES (:u, :p, 'siswa', 1, :cb)",
        {"u": username, "p": hash_password(password), "cb": created_by},
    )
    user_id = res.lastrowid
    db.execute(
        "INSERT INTO siswa_profil (user_id, nama_lengkap, tanggal_lahir, jenis_kelamin, kelas, nama_sekolah) "
        "VALUES (:uid, :nama, :tgl, :jk, :kelas, :sekolah)",
        {"uid": user_id, "nama": nama_lengkap, "tgl": tanggal_lahir, "jk": jenis_kelamin,
         "kelas": kelas, "sekolah": nama_sekolah},
    )
    return user_id


def get_siswa_profil(user_id: int):
    return db.fetch_one(
        "SELECT u.username, sp.* FROM siswa_profil sp JOIN users u ON u.id = sp.user_id "
        "WHERE sp.user_id = :uid",
        {"uid": user_id},
    )


def list_siswa_by_guru(guru_id: int):
    return db.fetch_all(
        "SELECT u.id AS user_id, u.username, sp.nama_lengkap, sp.tanggal_lahir, "
        "sp.jenis_kelamin, sp.kelas, sp.nama_sekolah "
        "FROM users u JOIN siswa_profil sp ON sp.user_id = u.id "
        "WHERE u.created_by = :gid ORDER BY sp.kelas, sp.nama_lengkap",
        {"gid": guru_id},
    )


def render_login_form():
    st.title("📚 Aplikasi Latihan Soal Ujian AI")
    st.subheader("Masuk")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Masuk", type="primary", use_container_width=True)
    if submitted:
        if not username or not password:
            st.error("Isi username dan password.")
        elif login(username, password):
            st.rerun()
        else:
            st.error("Username atau password salah.")
    st.caption("Belum punya akun? Hubungi guru/gurumu — akun siswa dibuatkan oleh guru, "
               "bukan mendaftar sendiri.")


def render_force_change_password():
    user = current_user()
    st.title("🔑 Ganti Password")
    st.info("Ini login pertamamu. Untuk keamanan, ganti dulu password bawaan sebelum lanjut.")
    with st.form("change_password_form"):
        new_pw = st.text_input("Password baru", type="password")
        new_pw2 = st.text_input("Ulangi password baru", type="password")
        submitted = st.form_submit_button("Simpan Password Baru", type="primary", use_container_width=True)
    if submitted:
        if len(new_pw) < 6:
            st.error("Password minimal 6 karakter.")
        elif new_pw != new_pw2:
            st.error("Konfirmasi password tidak cocok.")
        else:
            change_password(user["id"], new_pw)
            st.success("Password berhasil diganti.")
            st.rerun()
