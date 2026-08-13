-- Skema database Aplikasi Latihan Soal Ujian
-- Kompatibel dengan MySQL 8 / MariaDB 10.x (termasuk Aiven MySQL).
-- Jalankan sekali saat setup awal (modules/db.py -> init_schema() memanggil
-- file ini secara otomatis, aman dijalankan berulang karena pakai
-- `CREATE TABLE IF NOT EXISTS`).

CREATE TABLE IF NOT EXISTS users (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    username      VARCHAR(64)  NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role          ENUM('guru', 'siswa') NOT NULL,
    must_change_password TINYINT(1) NOT NULL DEFAULT 0,
    created_by    INT NULL,                 -- guru yang membuat akun ini (NULL untuk akun guru pertama)
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_users_created_by FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS siswa_profil (
    user_id       INT PRIMARY KEY,
    nama_lengkap  VARCHAR(150) NOT NULL,
    tanggal_lahir DATE NOT NULL,
    jenis_kelamin ENUM('L', 'P') NOT NULL,
    kelas         VARCHAR(50)  NOT NULL,
    nama_sekolah  VARCHAR(150) NOT NULL,
    CONSTRAINT fk_siswa_profil_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS paket_soal (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    nama         VARCHAR(150) NOT NULL,
    dibuat_oleh  INT NOT NULL,
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_paket_soal_guru FOREIGN KEY (dibuat_oleh) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS soal (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    paket_id          INT NOT NULL,
    nomor             INT NOT NULL,
    teks_soal         TEXT NOT NULL,
    opsi_json         JSON NOT NULL,        -- {"A": "...", "B": "...", "C": "...", "D": "..."}
    multi_answer      TINYINT(1) NOT NULL DEFAULT 0,
    n_correct         TINYINT NOT NULL DEFAULT 1,
    gambar_pendukung  LONGBLOB NULL,        -- potongan gambar tabel/grafik, nullable
    CONSTRAINT fk_soal_paket FOREIGN KEY (paket_id) REFERENCES paket_soal(id) ON DELETE CASCADE,
    UNIQUE KEY uq_soal_paket_nomor (paket_id, nomor)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Kontrol akses: paket soal mana yang boleh dikerjakan siswa mana.
-- Ini yang memastikan paket soal tidak beredar tanpa terkendali — siswa
-- hanya bisa melihat & mengerjakan paket yang eksplisit diizinkan gurunya.
CREATE TABLE IF NOT EXISTS akses_paket (
    siswa_user_id  INT NOT NULL,
    paket_id       INT NOT NULL,
    diberikan_oleh INT NOT NULL,
    diberikan_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (siswa_user_id, paket_id),
    CONSTRAINT fk_akses_siswa FOREIGN KEY (siswa_user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_akses_paket FOREIGN KEY (paket_id) REFERENCES paket_soal(id) ON DELETE CASCADE,
    CONSTRAINT fk_akses_guru FOREIGN KEY (diberikan_oleh) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS hasil_ujian (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    siswa_user_id  INT NOT NULL,
    paket_id       INT NOT NULL,
    status         ENUM('menunggu', 'selesai') NOT NULL DEFAULT 'menunggu',
    skor           INT NULL,             -- NULL selama status='menunggu' (belum dianalisis AI)
    total_soal     INT NOT NULL,
    dikerjakan_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,   -- saat siswa submit jawaban
    dianalisis_at  TIMESTAMP NULL,                                -- saat guru menjalankan analisa AI
    dianalisis_oleh INT NULL,                                     -- guru yang menjalankan analisa
    CONSTRAINT fk_hasil_siswa FOREIGN KEY (siswa_user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_hasil_paket FOREIGN KEY (paket_id) REFERENCES paket_soal(id) ON DELETE CASCADE,
    CONSTRAINT fk_hasil_guru FOREIGN KEY (dianalisis_oleh) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS jawaban_detail (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    hasil_ujian_id   INT NOT NULL,
    soal_id          INT NOT NULL,
    jawaban_siswa    VARCHAR(10) NOT NULL DEFAULT '',   -- mis. "A" atau "A,C"
    jawaban_benar_ai VARCHAR(10) NULL,                  -- diisi AI saat guru menjalankan analisa
    penjelasan_ai    TEXT NULL,
    is_correct       TINYINT(1) NULL,                   -- NULL sampai dianalisis
    CONSTRAINT fk_jawaban_hasil FOREIGN KEY (hasil_ujian_id) REFERENCES hasil_ujian(id) ON DELETE CASCADE,
    CONSTRAINT fk_jawaban_soal FOREIGN KEY (soal_id) REFERENCES soal(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
