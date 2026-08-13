"""Script CLI untuk membuat akun GURU (dijalankan dari terminal, bukan dari
UI publik) — supaya tidak sembarang orang bisa mendaftar sendiri jadi guru.

Jalankan sekali untuk membuat akun guru pertama, atau kapan saja untuk
menambah akun guru lain.

Cara pakai (dari dalam folder exam_app/, dengan .streamlit/secrets.toml
sudah berisi kredensial MySQL yang benar):

    python scripts/create_guru.py <username> <password>

Contoh:
    python scripts/create_guru.py bu_siti "PasswordAman123!"
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules import auth_db, db  # noqa: E402


def main():
    if len(sys.argv) != 3:
        print("Pemakaian: python scripts/create_guru.py <username> <password>")
        sys.exit(1)

    username, password = sys.argv[1], sys.argv[2]
    if len(password) < 8:
        print("Password minimal 8 karakter.")
        sys.exit(1)

    db.init_schema()

    if auth_db.username_exists(username):
        print(f"Username '{username}' sudah dipakai. Pilih username lain.")
        sys.exit(1)

    user_id = auth_db.create_guru(username, password)
    print(f"✅ Akun guru '{username}' berhasil dibuat (id={user_id}).")
    print("Silakan login lewat aplikasi dengan username & password tsb.")


if __name__ == "__main__":
    main()
