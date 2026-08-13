import streamlit as st

from modules import auth_db, db
from modules.auth import get_gemini_api_key

st.set_page_config(page_title="Latihan Soal Ujian AI", page_icon="📚", layout="wide")

# Pastikan skema tabel sudah ada (aman dipanggil berulang; hanya benar2
# membuat tabel kalau belum ada).
try:
    db.init_schema()
except Exception as e:
    st.error(
        "Tidak bisa terhubung ke database MySQL. Periksa konfigurasi "
        f"`[mysql]` di `.streamlit/secrets.toml`.\n\nDetail teknis: {e}"
    )
    st.stop()

if not auth_db.is_logged_in():
    auth_db.render_login_form()
    st.stop()

user = auth_db.current_user()

if user["must_change_password"]:
    auth_db.render_force_change_password()
    st.stop()

# --- Sidebar: info akun, API key, logout ---
with st.sidebar:
    st.markdown(f"**{user['username']}** · {user['role']}")
    if st.button("Keluar", use_container_width=True):
        auth_db.logout()
        st.rerun()

    st.divider()
    st.header("🔑 Gemini API Key")
    secret_key = st.secrets.get("GEMINI_API_KEY", "")
    if secret_key:
        get_gemini_api_key()
        st.success("Dimuat dari secrets ✅")
    elif user["role"] == "guru":
        manual_key = st.text_input(
            "Masukkan API key manual (sementara, hanya sesi ini)",
            type="password", value=st.session_state.get("gemini_api_key", ""),
        )
        if manual_key:
            st.session_state["gemini_api_key"] = manual_key
    else:
        st.caption("Belum dikonfigurasi guru/admin.")
    st.caption("Model: **gemini-2.5-flash**")

# --- Routing berbasis peran ---
if user["role"] == "guru":
    pages = [
        st.Page("pages/1_Upload_Soal.py", title="Upload Soal", icon="📤", default=True),
        st.Page("pages/3_Kelola_Siswa.py", title="Kelola Siswa", icon="👩‍🏫"),
    ]
else:
    pages = [
        st.Page("pages/2_Kerjakan_Soal.py", title="Kerjakan Soal", icon="📝", default=True),
        st.Page("pages/4_Riwayat_Nilai.py", title="Riwayat Nilai", icon="📊"),
    ]

pg = st.navigation(pages, position="sidebar")
pg.run()
