# STT Engine — Voice-to-Text (Faster-Whisper + FastAPI + Vue)

## Daftar Bab

- [Bab 1 — Arsitektur](#bab-1--arsitektur)
- [Bab 2 — Database](#bab-2--database)
- [Bab 3 — Backend](#bab-3--backend)
- [Bab 4 — Frontend](#bab-4--frontend)
- [Bab 5 — Menjalankan di Laptop GPU](#bab-5--menjalankan-di-laptop-gpu)
- [Bab 6 — Status Fitur](#bab-6--status-fitur)

---

## Bab 1 — Arsitektur

```
[Client] --chunk audio via WebSocket--> [FastAPI: buffer + resample 16kHz + Silero VAD]
  --> [Faster-Whisper: large-v3-turbo FP16/INT8] --> [teks ke client]
```

Dua mode: `POST /api/v1/transcribe` (upload file) dan `WS /ws/v1/transcribe-stream`
(streaming PCM 16-bit 16kHz mono, buffer ~1,5 dtk). Detail implementasi:
`Architecture_and_Implementation_Documentation.md`, blueprint asli:
`Blueprint System Architecture.txt`.

---

## Bab 2 — Database

Dual-DB via SQLAlchemy di `app/auth.py`, dipilih lewat env `DATABASE_URL`:

| Kebutuhan | URL | Keterangan |
|---|---|---|
| Testing / lokal | _(kosong)_ → `sqlite:///./data/stt.db` | Nol setup, 1 file |
| Data produksi | `postgresql+psycopg://user:pass@host:5432/stt` | Concurrent write aman |

Env lama `STT_DB=/path/ke.db` tetap dibaca sebagai SQLite (kompatibel mundur).
Tabel dibuat otomatis saat app start (`Base.metadata.create_all`), tanpa migrasi manual:

- `users(username PK, salt, pwdhash)` — login, hash PBKDF2-SHA256
- `history(id, username, at, source, lang, text)` — riwayat transkrip per user
- `resets(token PK, username, exp)` — token lupa password, berlaku 30 menit

### 2.1 SQLite (testing)

Tidak perlu apa-apa. Jalankan app, file `data/` dibuat sendiri (di-ignore git).

### 2.2 PostgreSQL (data)

Butuh server Postgres + driver `psycopg[binary]` (sudah di `requirements.txt`).
Contoh dengan superuser `postgres` / password `postgres123`:

```sql
-- psql / pgAdmin, login sebagai postgres
CREATE DATABASE stt;
```

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres123@localhost:5432/stt
```

User terpisah (disarankan untuk produksi):

```sql
CREATE USER stt WITH PASSWORD 'ganti-ini';
GRANT ALL PRIVILEGES ON DATABASE stt TO stt;
-- di dalam DB stt:
GRANT ALL ON SCHEMA public TO stt;
```

```env
DATABASE_URL=postgresql+psycopg://stt:ganti-ini@localhost:5432/stt
```

### 2.3 Env terkait

Lihat `.env.example`: `DATABASE_URL`, `JWT_SECRET` (wajib diganti di produksi!),
`JWT_EXP_HOURS`, `ADMIN_USER`, `ADMIN_PASS` (seed admin saat tabel kosong),
`STT_MODEL` (`tiny` di CPU kentang, `large-v3-turbo` di GPU).

---

## Bab 3 — Backend

Struktur `app/`: `main.py` (REST + WS + serve frontend), `stt_engine.py`
(wrapper Faster-Whisper lazy-load, CPU otomatis `int8`, model via `STT_MODEL`),
`auth.py` (JWT + dual-DB), `utils.py` (temp file + normalisasi ffmpeg 16kHz mono).

Auth endpoints: `POST /api/v1/auth/login`, `POST /api/v1/auth/forgot`,
`POST /api/v1/auth/reset`, `GET /api/v1/me`, `GET /api/v1/history`.
Transcribe/WS tetap bisa anonim, tapi riwayat hanya disimpan bila ada token
(REST: header `Authorization: Bearer`, WS: query `?token=`).

Install:

```bash
# GPU (CUDA 12.x)
pip install -r requirements.txt
# CPU saja
pip install -r requirements.cpu.txt
```

---

## Bab 4 — Frontend

`frontend/` adalah halaman terpisah (Tailwind CDN + SweetAlert2, tanpa build-step),
disajikan otomatis oleh backend di `/`:

- `login.html`, `forgot.html`, `reset.html` — alur auth sendiri-sendiri
- `dashboard.html` — layout sendiri: sidebar collapsible (tombol ⇔, ingat posisi),
  header (judul + health model/device + Keluar), konten (Dashboard, Transcribe,
  Riwayat, Pengaturan), footer
- `assets/auth.js` — helper token + wrapper SweetAlert untuk semua halaman

---

## Bab 5 — Menjalankan di Laptop GPU

### 5.1 Docker Compose (disarankan)

```powershell
git pull
# opsional: salin .env.example -> .env lalu isi POSTGRES_PASSWORD, JWT_SECRET, ADMIN_PASS
docker compose up -d --build
docker compose logs -f api
# buka http://localhost:8000/ -> redirect ke login/dashboard
```

Untuk GPU NVIDIA: install NVIDIA Container Toolkit, lalu uncomment blok
`deploy.resources.reservations` di `docker-compose.yml`.

### 5.2 Manual (tanpa Docker)

```powershell
git pull
pip install -r requirements.txt
$env:STT_MODEL="large-v3-turbo"
$env:ADMIN_PASS="ganti-ini"
$env:DATABASE_URL="postgresql+psycopg://postgres:postgres123@localhost:5432/stt"
uvicorn app.main:app --port 8000
# buka http://localhost:8000/ -> redirect ke login/dashboard
```

---

## Bab 6 — Status Fitur

### ✅ Sudah selesai

- [x] Blueprint + dokumentasi arsitektur
- [x] Backend FastAPI: REST upload, WS streaming, `/health`
- [x] Inference Faster-Whisper lazy-load (CPU `int8` / GPU `float16`, `STT_MODEL`)
- [x] Halaman Login / Lupa / Reset password terpisah
- [x] Dashboard: sidebar collapsible, header, footer (Tailwind + SweetAlert2)
- [x] Menu Transcribe (upload + mic), Riwayat, Pengaturan
- [x] Auth JWT + riwayat per user, dual-DB SQLite/Postgres
- [x] Ekspor transkrip TXT / SRT / VTT per riwayat
- [x] Docker Compose FastAPI + Postgres + panduan GPU
- [x] Halaman Model & Perangkat (`GET /api/v1/system`, ganti model runtime)
- [x] README 5 bab

### ⬜ Belum dikerjakan / belum dibuat

- [ ] Manajemen user & roles (admin vs user biasa)
- [ ] Antrean file besar (Celery + Redis)
- [ ] Reset password via email (sekarang token dikembalikan langsung)
- [ ] Batch upload banyak file sekaligus
- [ ] API key untuk pemakaian aplikasi lain
- [ ] Log audit aktivitas user
- [ ] Tes otomatis (pytest) + CI
