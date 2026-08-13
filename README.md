# 📚 Aplikasi Latihan Soal Ujian Berbasis AI (Streamlit + Gemini + MySQL)

Aplikasi latihan soal pilihan ganda dengan login guru/siswa: guru unggah PDF
soal & mengatur siapa yang boleh mengerjakannya, siswa login dan mengerjakan,
lalu AI (Gemini 2.5 Flash) menentukan jawaban benar + penjelasan singkat,
menghitung skor, dan hasilnya tersimpan sebagai riwayat nilai + bisa diunduh
PDF.

**AI dipakai seminim mungkin** — hanya untuk tugas yang benar-benar butuh
penalaran (menentukan jawaban benar + menjelaskan alasannya). Membaca &
memecah PDF menjadi soal terstruktur dilakukan murni dengan Python
(`pdfplumber` + `PyMuPDF`), tanpa panggilan API sama sekali.

## Cara Kerja

1. **Guru login**, membuka halaman **📤 Upload Soal**, mengunggah PDF, lalu
   menekan **🧩 Proses PDF (Parser Bawaan — Gratis, Tanpa AI)**. Parser
   membaca posisi teks & gambar PDF untuk memecah soal dan memotong presisi
   tabel/grafik pendukungnya — tanpa AI. Ada tombol fallback AI opsional
   untuk PDF berlayout tidak biasa. Guru meninjau/menyunting hasil sebelum
   disimpan sebagai "paket soal" (tersimpan di MySQL, termasuk gambar
   pendukungnya sebagai BLOB).
2. **Guru membuka halaman 👩‍🏫 Kelola Siswa** untuk:
   - **Membuat akun siswa** (username, password awal, nama lengkap, tanggal
     lahir, jenis kelamin, kelas, nama sekolah). Siswa **tidak mendaftar
     sendiri** — akun dibuatkan guru, supaya terkontrol siapa saja yang
     punya akses.
   - **Memilih paket soal mana yang boleh dikerjakan siswa mana** (per
     siswa, atau sekaligus per kelas). Paket soal tidak otomatis terlihat
     semua siswa — harus eksplisit diberi akses.
3. **Siswa login** (password awal wajib diganti saat login pertama), buka
   halaman **📝 Kerjakan Soal** — hanya paket yang diizinkan gurunya yang
   muncul. Jawab tiap soal, lalu tekan **Analisa dengan AI**: AI menentukan
   jawaban benar + penjelasan singkat (hanya potongan gambar per-soal yang
   dikirim ke API, bukan seluruh PDF, supaya hemat token), skor dihitung
   (benar = 1, salah = 0), dan hasil otomatis tersimpan ke riwayat nilai
   siswa tsb.
4. Siswa bisa buka halaman **📊 Riwayat Nilai** kapan saja untuk melihat
   semua hasil pengerjaan sebelumnya dan mengunduh ulang PDF-nya.

## Arsitektur & Skema Database

Semua data (akun, paket soal, gambar pendukung, kontrol akses, riwayat
nilai) tersimpan di **MySQL** — dirancang untuk dipakai dengan
[Aiven MySQL](https://aiven.io/mysql) (managed, ada free tier), tapi
kompatibel dengan MySQL/MariaDB manapun. Skema lengkap ada di
`sql/schema.sql`, dibuat otomatis saat aplikasi pertama kali jalan.

```
users            — akun guru & siswa (password di-hash bcrypt)
siswa_profil     — nama, tanggal lahir, jenis kelamin, kelas, sekolah
paket_soal       — paket soal, dibuat oleh guru
soal             — tiap soal per paket, termasuk gambar pendukung (BLOB)
akses_paket      — kontrol siapa boleh akses paket apa (+ siapa yg memberi)
hasil_ujian      — skor per pengerjaan siswa
jawaban_detail   — detail jawaban per soal per pengerjaan
```

## Instalasi

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 1. Setup database MySQL (Aiven)

1. Buat service MySQL baru di [Aiven Console](https://console.aiven.io/)
   (free tier tersedia).
2. Dari halaman service, catat: **Host**, **Port**, **User** (biasanya
   `avnadmin`), **Password**, dan nama database (biasanya `defaultdb`).
   Kalau instance-mu mewajibkan SSL dengan CA tertentu, salin juga isi
   sertifikat **CA Certificate**-nya.

### 2. Isi kredensial di `.streamlit/secrets.toml`

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Edit file tsb:

```toml
GEMINI_API_KEY = "AIzaSy...isi_api_key_kamu"

[mysql]
host = "xxx.aivencloud.com"
port = 12345
user = "avnadmin"
password = "isi_password_aiven"
database = "defaultdb"
```

Dapatkan Gemini API key gratis di https://aistudio.google.com/apikey.

> `.streamlit/secrets.toml` sudah masuk `.gitignore` — jangan pernah commit
> file ini. Untuk deploy ke **Streamlit Community Cloud**, isi nilai yang
> sama lewat menu *App settings → Secrets* di dashboard.

### 3. Buat akun guru pertama

Karena guru **tidak bisa mendaftar sendiri lewat UI** (supaya tidak
sembarang orang jadi guru), buat akun guru pertama lewat terminal:

```bash
python scripts/create_guru.py <username> <password>
```

Contoh:

```bash
python scripts/create_guru.py bu_siti "PasswordAman123!"
```

Script ini juga otomatis membuat semua tabel di database kalau belum ada.

## Menjalankan

```bash
streamlit run app.py
```

Buka `http://localhost:8501`, login dengan akun guru yang baru dibuat.

## Struktur Proyek

```
exam_app/
├── app.py                          # Login gate + routing berbasis peran (st.navigation)
├── pages/
│   ├── 1_Upload_Soal.py            # Guru: upload & proses PDF jadi soal
│   ├── 2_Kerjakan_Soal.py          # Siswa: kerjakan soal yg diizinkan, analisa AI
│   ├── 3_Kelola_Siswa.py           # Guru: buat akun siswa, atur akses paket soal
│   └── 4_Riwayat_Nilai.py          # Siswa: lihat & unduh ulang hasil sebelumnya
├── modules/
│   ├── db.py                       # Koneksi MySQL (SQLAlchemy, cached)
│   ├── auth_db.py                  # Login, sesi, buat akun guru/siswa, ganti password
│   ├── storage.py                  # Paket soal, kontrol akses, hasil ujian (di MySQL)
│   ├── text_parser.py              # Parser PDF UTAMA — murni Python, TANPA AI
│   ├── pdf_parser.py               # PDF -> gambar per halaman (dipakai fallback AI saja)
│   ├── gemini_client.py            # Panggilan ke Gemini (analisis jawaban + fallback parse)
│   ├── pdf_report.py               # Buat PDF hasil (ReportLab)
│   └── auth.py                     # Resolusi Gemini API key (secrets.toml / manual)
├── scripts/
│   └── create_guru.py              # CLI bootstrap akun guru pertama
├── sql/
│   └── schema.sql                  # Skema tabel MySQL (auto-dijalankan saat start)
└── requirements.txt
```

## Login & Kontrol Akses

- **Guru**: dibuat lewat `scripts/create_guru.py` (terminal), bukan lewat
  UI publik.
- **Siswa**: dibuat oleh guru lewat halaman **Kelola Siswa**, lengkap dengan
  profil (nama, tanggal lahir, jenis kelamin, kelas, sekolah — usia
  dihitung otomatis dari tanggal lahir). Password awal **wajib diganti**
  siswa saat login pertama kali.
- **Paket soal dibatasi per siswa** lewat tabel `akses_paket` — siswa hanya
  melihat paket yang eksplisit diberikan gurunya (satu per satu, atau
  sekaligus per kelas). Ini memastikan paket soal tidak beredar tanpa
  terkendali.
- **Sesi login** disimpan di `st.session_state` — bertahan selama tab
  browser masih terhubung ke sesi Streamlit yang sama (termasuk saat
  berpindah halaman), tapi **hilang kalau tab di-refresh penuh (F5)** atau
  ditutup. Ini keterbatasan yang disengaja untuk versi ini supaya scope
  tetap terkendali. Kalau butuh sesi yang benar-benar persisten lintas
  refresh browser, bisa ditingkatkan nanti dengan cookie session (mis. pakai
  `streamlit-authenticator` atau `extra-streamlit-components`).
- **Reset password oleh guru** (kalau siswa lupa password) belum ada di
  UI — untuk sementara bisa dilakukan manual lewat query database, atau
  saya bisa bantu tambahkan halaman untuk ini kalau diperlukan.

## Publikasi (GitHub + Streamlit Community Cloud)

1. Push folder ini ke repo GitHub (`.streamlit/secrets.toml` otomatis
   tidak ikut ter-push karena ada di `.gitignore`).
2. Di [share.streamlit.io](https://share.streamlit.io/), hubungkan ke repo,
   pilih `app.py` sebagai entry point.
3. Di *App settings → Secrets*, isi `GEMINI_API_KEY` dan bagian `[mysql]`
   persis seperti isi `.streamlit/secrets.toml` lokal kamu.
4. Karena semua data (paket soal, akun, hasil ujian) sudah di MySQL
   (bukan file lokal), data **tidak akan hilang** saat aplikasi di-redeploy
   atau di-restart otomatis — beda dengan versi sebelumnya yang masih
   pakai file lokal.
5. Jalankan `python scripts/create_guru.py <user> <pass>` dari komputer
   lokal (dengan `secrets.toml` menunjuk ke database Aiven yang sama) untuk
   membuat akun guru pertama di database produksi.

## Catatan Lain

- SDK Gemini yang dipakai adalah paket resmi terbaru **`google-genai`**
  (bukan `google-generativeai` yang sudah deprecated).
- Gambar pendukung tiap soal disimpan sebagai **BLOB langsung di MySQL**
  (bukan object storage terpisah) — pilihan yang lebih sederhana untuk
  skala pemakaian wajar (puluhan-ratusan paket soal).
- **Menghapus paket soal akan ikut menghapus riwayat nilai siswa** yang
  terkait paket tsb (`ON DELETE CASCADE` di skema). Ini trade-off desain
  yang disengaja demi kesederhanaan — kalau butuh riwayat nilai tetap ada
  walau paket soalnya dihapus, kabari saya, skemanya bisa disesuaikan
  (mis. ganti jadi `ON DELETE SET NULL` + simpan snapshot nama paket).
- `text_parser.py` mengasumsikan tiap soal (nomor + teks + opsi) berada
  dalam satu halaman yang sama. Soal yang terpotong lintas halaman akan
  dilewati parser bawaan — guru bisa menambahkannya manual, atau coba
  tombol fallback AI.
- Model Gemini default: `gemini-2.5-flash`, bisa diganti di
  `modules/gemini_client.py` (variabel `MODEL_NAME`).
