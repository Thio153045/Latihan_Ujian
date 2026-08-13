"""Koneksi database MySQL (mis. Aiven MySQL) untuk aplikasi.

Kredensial dibaca dari st.secrets["mysql"]:
    host, port, user, password, database
    ssl_ca (opsional) -> ISI sertifikat CA Aiven (bukan path file), supaya
    bisa disimpan langsung di secrets.toml / Streamlit Cloud secrets tanpa
    perlu upload file terpisah. Ditulis ke file sementara saat runtime.

Koneksi (engine) di-cache dengan st.cache_resource supaya tidak membuka
koneksi baru setiap kali Streamlit rerun script (yang terjadi di hampir
tiap interaksi pengguna).
"""

import os

import streamlit as st
from sqlalchemy import create_engine, text

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sql", "schema.sql")


@st.cache_resource(show_spinner=False)
def get_engine():
    cfg = st.secrets["mysql"]
    connect_args = {}

    ssl_ca = cfg.get("ssl_ca")
    if ssl_ca:
        ca_path = "/tmp/aiven_ca.pem"
        with open(ca_path, "w", encoding="utf-8") as f:
            f.write(ssl_ca)
        connect_args["ssl"] = {"ca": ca_path}

    url = (
        f"mysql+pymysql://{cfg['user']}:{cfg['password']}"
        f"@{cfg['host']}:{cfg.get('port', 3306)}/{cfg['database']}?charset=utf8mb4"
    )
    return create_engine(url, connect_args=connect_args, pool_pre_ping=True, pool_recycle=280)


def init_schema():
    """Membuat semua tabel dari sql/schema.sql jika belum ada.
    Aman dipanggil berulang kali (pakai CREATE TABLE IF NOT EXISTS)."""
    engine = get_engine()
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        raw_sql = f.read()
    statements = [s.strip() for s in raw_sql.split(";") if s.strip()]
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))


def fetch_all(sql: str, params: dict | None = None) -> list[dict]:
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        return [dict(row._mapping) for row in result]


def fetch_one(sql: str, params: dict | None = None) -> dict | None:
    rows = fetch_all(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: dict | None = None):
    """Untuk INSERT/UPDATE/DELETE. Mengembalikan objek Result SQLAlchemy
    (mis. untuk mengambil `.lastrowid` setelah INSERT)."""
    engine = get_engine()
    with engine.begin() as conn:
        return conn.execute(text(sql), params or {})
