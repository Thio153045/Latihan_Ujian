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
    """Membuat semua tabel dari sql/schema.sql jika belum ada, lalu
    menjalankan migrasi ringan untuk instalasi yang sudah ada sebelumnya
    (aman dipanggil berulang kali)."""
    engine = get_engine()
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        raw_sql = f.read()
    statements = [s.strip() for s in raw_sql.split(";") if s.strip()]
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
    _run_migrations(engine)


# Migrasi untuk instalasi lama: memisahkan status pengumpulan jawaban siswa
# ("menunggu" analisa guru) dari status sudah dinilai ("selesai"). Dicek
# lewat information_schema dulu (bukan try/except tebak pesan error) supaya
# aman dipanggil berulang di MySQL maupun MariaDB — pesan error "sudah ada"
# beda-beda tiap versi, jadi lebih andal dicek langsung daripada ditebak.

def _column_exists(engine, table: str, column: str) -> bool:
    row = _fetch_one_raw(
        engine,
        "SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
        "AND TABLE_NAME = :t AND COLUMN_NAME = :c",
        {"t": table, "c": column},
    )
    return row is not None


def _constraint_exists(engine, table: str, constraint: str) -> bool:
    row = _fetch_one_raw(
        engine,
        "SELECT 1 FROM information_schema.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA = DATABASE() "
        "AND TABLE_NAME = :t AND CONSTRAINT_NAME = :c",
        {"t": table, "c": constraint},
    )
    return row is not None


def _fetch_one_raw(engine, sql: str, params: dict):
    with engine.connect() as conn:
        result = conn.execute(text(sql), params)
        row = result.fetchone()
        return dict(row._mapping) if row else None


def _run_migrations(engine):
    if not _column_exists(engine, "hasil_ujian", "status"):
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE hasil_ujian ADD COLUMN status ENUM('menunggu','selesai') "
                "NOT NULL DEFAULT 'selesai' AFTER paket_id"
            ))

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE hasil_ujian MODIFY COLUMN skor INT NULL"))

    if not _column_exists(engine, "hasil_ujian", "dianalisis_at"):
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE hasil_ujian ADD COLUMN dianalisis_at TIMESTAMP NULL AFTER dikerjakan_at"
            ))

    if not _column_exists(engine, "hasil_ujian", "dianalisis_oleh"):
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE hasil_ujian ADD COLUMN dianalisis_oleh INT NULL AFTER dianalisis_at"
            ))

    if not _constraint_exists(engine, "hasil_ujian", "fk_hasil_guru"):
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE hasil_ujian ADD CONSTRAINT fk_hasil_guru FOREIGN KEY (dianalisis_oleh) "
                "REFERENCES users(id) ON DELETE SET NULL"
            ))

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE jawaban_detail MODIFY COLUMN jawaban_benar_ai VARCHAR(10) NULL"))
        conn.execute(text("ALTER TABLE jawaban_detail MODIFY COLUMN penjelasan_ai TEXT NULL"))
        conn.execute(text("ALTER TABLE jawaban_detail MODIFY COLUMN is_correct TINYINT(1) NULL"))
        # Data lama (sebelum migrasi ini) sudah pasti berstatus selesai
        # (skor-nya sudah terisi) — isi dianalisis_at retroaktif dari waktu submit.
        conn.execute(text(
            "UPDATE hasil_ujian SET dianalisis_at = dikerjakan_at "
            "WHERE dianalisis_at IS NULL AND skor IS NOT NULL"
        ))


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
