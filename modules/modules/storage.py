"""Penyimpanan paket soal, kontrol akses, dan hasil ujian di MySQL
(menggantikan versi penyimpanan file-lokal sebelumnya). Gambar pendukung
tiap soal disimpan sebagai BLOB langsung di tabel `soal` — sengaja dipilih
supaya tidak perlu layanan object storage terpisah untuk skala pemakaian
yang wajar."""

import io
import json

from PIL import Image

from modules import db


# --- paket soal & soal ---

def save_package(name: str, questions: list, guru_id: int) -> int:
    """questions: list of dict dengan number, question, options,
    multi_answer, n_correct, dan opsional "image" (PIL.Image atau None)."""
    res = db.execute(
        "INSERT INTO paket_soal (nama, dibuat_oleh) VALUES (:n, :g)",
        {"n": name, "g": guru_id},
    )
    paket_id = res.lastrowid

    for q in questions:
        img = q.get("image")
        img_bytes = None
        if img is not None:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            img_bytes = buf.getvalue()
        db.execute(
            "INSERT INTO soal (paket_id, nomor, teks_soal, opsi_json, multi_answer, n_correct, gambar_pendukung) "
            "VALUES (:pid, :no, :teks, :opsi, :multi, :ncorrect, :img)",
            {
                "pid": paket_id, "no": q["number"], "teks": q["question"],
                "opsi": json.dumps(q["options"], ensure_ascii=False),
                "multi": int(q.get("multi_answer", False)), "ncorrect": q.get("n_correct", 1),
                "img": img_bytes,
            },
        )
    return paket_id


def list_packages_by_guru(guru_id: int) -> list:
    return db.fetch_all(
        "SELECT ps.id, ps.nama, ps.created_at, COUNT(s.id) AS jumlah_soal "
        "FROM paket_soal ps LEFT JOIN soal s ON s.paket_id = ps.id "
        "WHERE ps.dibuat_oleh = :g GROUP BY ps.id, ps.nama, ps.created_at ORDER BY ps.created_at DESC",
        {"g": guru_id},
    )


def list_accessible_packages(siswa_id: int) -> list:
    """Hanya paket yang BELUM pernah disubmit siswa ini (baik masih
    menunggu dianalisis maupun sudah selesai dinilai) — supaya begitu satu
    paket dikerjakan, siswa otomatis diarahkan ke paket berikutnya."""
    return db.fetch_all(
        "SELECT ps.id, ps.nama, COUNT(DISTINCT s.id) AS jumlah_soal "
        "FROM paket_soal ps "
        "JOIN akses_paket ap ON ap.paket_id = ps.id "
        "LEFT JOIN soal s ON s.paket_id = ps.id "
        "WHERE ap.siswa_user_id = :sid "
        "AND ps.id NOT IN (SELECT paket_id FROM hasil_ujian WHERE siswa_user_id = :sid) "
        "GROUP BY ps.id, ps.nama ORDER BY ps.nama",
        {"sid": siswa_id},
    )


def load_package(paket_id: int):
    """Mengembalikan (meta, question_images). meta punya keys id/name/
    questions (list of dict number/question/options/multi_answer/n_correct/
    has_visual). question_images: dict {number: PIL.Image}."""
    paket = db.fetch_one("SELECT * FROM paket_soal WHERE id = :p", {"p": paket_id})
    if paket is None:
        return None, {}

    soal_rows = db.fetch_all(
        "SELECT id, nomor, teks_soal, opsi_json, multi_answer, n_correct, gambar_pendukung "
        "FROM soal WHERE paket_id = :p ORDER BY nomor",
        {"p": paket_id},
    )

    questions, question_images = [], {}
    for row in soal_rows:
        opsi = row["opsi_json"]
        if isinstance(opsi, str):
            opsi = json.loads(opsi)
        questions.append({
            "id": row["id"],
            "number": row["nomor"],
            "question": row["teks_soal"],
            "options": opsi,
            "multi_answer": bool(row["multi_answer"]),
            "n_correct": row["n_correct"],
            "has_visual": row["gambar_pendukung"] is not None,
        })
        if row["gambar_pendukung"] is not None:
            question_images[row["nomor"]] = Image.open(io.BytesIO(bytes(row["gambar_pendukung"])))

    meta = {"id": paket["id"], "name": paket["nama"], "questions": questions}
    return meta, question_images


def delete_package(paket_id: int):
    db.execute("DELETE FROM paket_soal WHERE id = :p", {"p": paket_id})


# --- kontrol akses (paket soal tidak beredar tanpa terkendali) ---

def grant_access(siswa_id: int, paket_id: int, guru_id: int):
    db.execute(
        "INSERT IGNORE INTO akses_paket (siswa_user_id, paket_id, diberikan_oleh) VALUES (:s, :p, :g)",
        {"s": siswa_id, "p": paket_id, "g": guru_id},
    )


def revoke_access(siswa_id: int, paket_id: int):
    db.execute(
        "DELETE FROM akses_paket WHERE siswa_user_id = :s AND paket_id = :p",
        {"s": siswa_id, "p": paket_id},
    )


def get_access_map(guru_id: int) -> dict:
    """{siswa_user_id: {paket_id, ...}} untuk siswa-siswa milik guru ini."""
    rows = db.fetch_all(
        "SELECT ap.siswa_user_id, ap.paket_id FROM akses_paket ap "
        "JOIN users u ON u.id = ap.siswa_user_id WHERE u.created_by = :g",
        {"g": guru_id},
    )
    result: dict = {}
    for r in rows:
        result.setdefault(r["siswa_user_id"], set()).add(r["paket_id"])
    return result


# --- hasil ujian: submit (siswa) -> menunggu -> analisa (guru) -> selesai ---

def save_submission(siswa_id: int, paket_id: int, answers: dict) -> int:
    """Dipanggil siswa setelah selesai menjawab satu paket. Menyimpan
    jawaban MENTAH saja (belum ada penilaian AI) dengan status 'menunggu'.
    answers: {nomor_soal: [huruf, ...]}."""
    soal_rows = db.fetch_all(
        "SELECT id, nomor FROM soal WHERE paket_id = :p", {"p": paket_id}
    )
    res = db.execute(
        "INSERT INTO hasil_ujian (siswa_user_id, paket_id, status, skor, total_soal) "
        "VALUES (:s, :p, 'menunggu', NULL, :t)",
        {"s": siswa_id, "p": paket_id, "t": len(soal_rows)},
    )
    hasil_id = res.lastrowid

    for row in soal_rows:
        jawaban = answers.get(row["nomor"], [])
        db.execute(
            "INSERT INTO jawaban_detail (hasil_ujian_id, soal_id, jawaban_siswa) VALUES (:h, :s, :j)",
            {"h": hasil_id, "s": row["id"], "j": ",".join(jawaban)},
        )
    return hasil_id


def list_pending_submissions(guru_id: int, siswa_id: int = None, paket_id: int = None) -> list:
    """Submisi berstatus 'menunggu' milik siswa-siswa guru ini, siap
    dianalisis. Bisa difilter per siswa dan/atau per paket."""
    sql = (
        "SELECT hu.id, hu.dikerjakan_at, hu.total_soal, "
        "u.id AS siswa_id, sp.nama_lengkap, sp.kelas, sp.nama_sekolah, "
        "ps.id AS paket_id, ps.nama AS paket_nama "
        "FROM hasil_ujian hu "
        "JOIN users u ON u.id = hu.siswa_user_id "
        "JOIN siswa_profil sp ON sp.user_id = u.id "
        "JOIN paket_soal ps ON ps.id = hu.paket_id "
        "WHERE u.created_by = :g AND hu.status = 'menunggu'"
    )
    params = {"g": guru_id}
    if siswa_id:
        sql += " AND u.id = :sid"
        params["sid"] = siswa_id
    if paket_id:
        sql += " AND ps.id = :pid"
        params["pid"] = paket_id
    sql += " ORDER BY hu.dikerjakan_at ASC"
    return db.fetch_all(sql, params)


def list_completed_submissions(guru_id: int, siswa_id: int = None, paket_id: int = None) -> list:
    """Submisi berstatus 'selesai' (sudah dinilai AI) milik siswa-siswa
    guru ini. Bisa difilter per siswa dan/atau per paket."""
    sql = (
        "SELECT hu.id, hu.skor, hu.total_soal, hu.dikerjakan_at, hu.dianalisis_at, "
        "u.id AS siswa_id, sp.nama_lengkap, sp.kelas, sp.nama_sekolah, "
        "ps.id AS paket_id, ps.nama AS paket_nama "
        "FROM hasil_ujian hu "
        "JOIN users u ON u.id = hu.siswa_user_id "
        "JOIN siswa_profil sp ON sp.user_id = u.id "
        "JOIN paket_soal ps ON ps.id = hu.paket_id "
        "WHERE u.created_by = :g AND hu.status = 'selesai'"
    )
    params = {"g": guru_id}
    if siswa_id:
        sql += " AND u.id = :sid"
        params["sid"] = siswa_id
    if paket_id:
        sql += " AND ps.id = :pid"
        params["pid"] = paket_id
    sql += " ORDER BY hu.dianalisis_at DESC"
    return db.fetch_all(sql, params)


def get_submission_for_analysis(hasil_id: int):
    """Siapkan payload untuk dikirim ke gemini_client.analyze_answers():
    daftar soal + jawaban mentah siswa + gambar pendukung. Mengembalikan
    (questions_payload, question_images) atau (None, {}) kalau tidak ada."""
    rows = db.fetch_all(
        "SELECT jd.soal_id, jd.jawaban_siswa, s.nomor, s.teks_soal, s.opsi_json, "
        "s.multi_answer, s.n_correct, s.gambar_pendukung "
        "FROM jawaban_detail jd JOIN soal s ON s.id = jd.soal_id "
        "WHERE jd.hasil_ujian_id = :h ORDER BY s.nomor",
        {"h": hasil_id},
    )
    if not rows:
        return None, {}

    questions_payload, question_images = [], {}
    for row in rows:
        opsi = row["opsi_json"]
        if isinstance(opsi, str):
            opsi = json.loads(opsi)
        questions_payload.append({
            "number": row["nomor"],
            "question": row["teks_soal"],
            "options": opsi,
            "multi_answer": bool(row["multi_answer"]),
            "n_correct": row["n_correct"],
            "student_answer": row["jawaban_siswa"].split(",") if row["jawaban_siswa"] else [],
        })
        if row["gambar_pendukung"] is not None:
            question_images[row["nomor"]] = Image.open(io.BytesIO(bytes(row["gambar_pendukung"])))

    return questions_payload, question_images


def apply_analysis_result(hasil_id: int, guru_id: int, ai_result: list) -> int:
    """Terapkan hasil analisa AI (list of dict number/correct_answer/
    explanation) ke jawaban_detail, hitung skor, dan tandai hasil_ujian
    sebagai 'selesai'. Mengembalikan skor."""
    ai_by_number = {r["number"]: r for r in ai_result}
    rows = db.fetch_all(
        "SELECT jd.id, jd.jawaban_siswa, s.nomor "
        "FROM jawaban_detail jd JOIN soal s ON s.id = jd.soal_id "
        "WHERE jd.hasil_ujian_id = :h",
        {"h": hasil_id},
    )
    score = 0
    for row in rows:
        ai = ai_by_number.get(row["nomor"])
        if ai is None:
            continue
        correct = set(ai.get("correct_answer", []))
        student = set(row["jawaban_siswa"].split(",")) if row["jawaban_siswa"] else set()
        is_correct = student == correct and len(correct) > 0
        if is_correct:
            score += 1
        db.execute(
            "UPDATE jawaban_detail SET jawaban_benar_ai = :jb, penjelasan_ai = :pj, is_correct = :ic "
            "WHERE id = :id",
            {"jb": ",".join(sorted(correct)), "pj": ai.get("explanation", ""),
             "ic": int(is_correct), "id": row["id"]},
        )

    db.execute(
        "UPDATE hasil_ujian SET status = 'selesai', skor = :sk, "
        "dianalisis_at = CURRENT_TIMESTAMP, dianalisis_oleh = :g WHERE id = :h",
        {"sk": score, "g": guru_id, "h": hasil_id},
    )
    return score


def list_riwayat_siswa(siswa_id: int) -> list:
    return db.fetch_all(
        "SELECT hu.id, hu.status, hu.skor, hu.total_soal, hu.dikerjakan_at, ps.nama AS paket_nama "
        "FROM hasil_ujian hu JOIN paket_soal ps ON ps.id = hu.paket_id "
        "WHERE hu.siswa_user_id = :s ORDER BY hu.dikerjakan_at DESC",
        {"s": siswa_id},
    )


def load_hasil_detail(hasil_ujian_id: int):
    """Hanya bermakna untuk hasil_ujian berstatus 'selesai' (sudah dianalisis)."""
    header = db.fetch_one(
        "SELECT hu.*, ps.nama AS paket_nama FROM hasil_ujian hu "
        "JOIN paket_soal ps ON ps.id = hu.paket_id WHERE hu.id = :h",
        {"h": hasil_ujian_id},
    )
    if header is None:
        return None, [], {}

    rows = db.fetch_all(
        "SELECT jd.*, s.nomor, s.teks_soal, s.opsi_json, s.gambar_pendukung "
        "FROM jawaban_detail jd JOIN soal s ON s.id = jd.soal_id "
        "WHERE jd.hasil_ujian_id = :h ORDER BY s.nomor",
        {"h": hasil_ujian_id},
    )
    results, question_images = [], {}
    for row in rows:
        opsi = row["opsi_json"]
        if isinstance(opsi, str):
            opsi = json.loads(opsi)
        results.append({
            "number": row["nomor"],
            "question": row["teks_soal"],
            "options": opsi,
            "correct_answer": row["jawaban_benar_ai"].split(",") if row["jawaban_benar_ai"] else [],
            "student_answer": row["jawaban_siswa"].split(",") if row["jawaban_siswa"] else [],
            "is_correct": bool(row["is_correct"]),
            "explanation": row["penjelasan_ai"],
        })
        if row["gambar_pendukung"] is not None:
            question_images[row["nomor"]] = Image.open(io.BytesIO(bytes(row["gambar_pendukung"])))

    return header, results, question_images
