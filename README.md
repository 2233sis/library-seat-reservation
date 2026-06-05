# Library Seat Reservation System

> **Layer 2** of an AI-powered meta-software development pipeline (DTS114TC CW).
> The Notebook in `../Task1/DTS114_CW_Task1.ipynb` is **Layer 1** — it generates everything in this directory.

A Flask + SQLite seat-booking system for a university library. Eleven business rules, JWT-style auth via `itsdangerous`, single-page vanilla-JS frontend, container-ready, two-stage GitHub Actions CI.

---

## Project layout

```
Task2/
├── app.py                       Flask backend (~700 lines, AI-generated then human-audited)
├── requirements.txt             Python deps (pinned ranges)
├── ai_in_se_cw.yml              Conda env file (matches lab environment)
├── Dockerfile                   Production container (gunicorn + Python 3.11)
├── README.md                    This file
├── .gitignore
├── .github/workflows/ci.yml     Two-stage CI: test → build
├── templates/index.html         Single-page application
├── static/library_seat.png      Hero image (Qwen-Image-2512 generated)
├── docs/
│   ├── requirements.md          AI-generated SRS
│   ├── usecase_diagram.png      + .puml source
│   ├── sequence_diagram.png     + .puml source
│   ├── activity_diagram.png     + .puml source
│   ├── image_generation_audit.json   Records every AI image attempt
│   └── test_generation_audit.json    Records test-generation syntax check
└── tests/test_api.py            15 AI-generated pytest cases
```

---

## Quick start (local Python)

```bash
pip install -r requirements.txt
python app.py
# open http://localhost:5000
```

## Quick start (Docker — recommended)

```bash
docker build -t library-seat-reservation .
docker run -d -p 5000:5000 --name lsr library-seat-reservation
# open http://localhost:5000
```

To stop:
```bash
docker stop lsr && docker rm lsr
```

## Conda environment (matches the lab `ai_in_se_cw`)

```bash
conda env create -f ai_in_se_cw.yml
conda activate ai_in_se_cw
python app.py
```

## Default seeded users

| Username  | Password   | Role  |
|-----------|------------|-------|
| `admin`   | `admin123` | admin |
| `student1`| `student123` | user |

The database (`library.db`) is created on first run if missing, with a few sample seats (single + meeting rooms).

---

## API endpoints

| Method | Path | Auth | Purpose | FR |
|--------|------|------|---------|----|
| GET    | `/`                                       | -     | SPA homepage | - |
| POST   | `/api/register`                           | -     | sign up | - |
| POST   | `/api/login`                              | -     | issue token | FR-01 |
| GET    | `/api/seats`                              | -     | list seats with today's status | FR-09 |
| GET    | `/api/seats/<id>/schedule`                | -     | per-seat timetable | FR-09 |
| POST   | `/api/bookings`                           | user  | create booking | FR-02/03/05/06 |
| GET    | `/api/my-bookings`                        | user  | list own bookings | - |
| DELETE | `/api/bookings/<id>`                      | user  | cancel (≥15 min before) | FR-04 |
| POST   | `/api/bookings/<id>/checkin`              | user  | check in | FR-07 |
| GET    | `/api/admin/violations`                   | admin | violations log | FR-08 |
| GET    | `/api/admin/blacklist`                    | admin | blacklist | FR-10 |
| POST   | `/api/admin/blacklist`                    | admin | blacklist user | FR-10 |
| DELETE | `/api/admin/blacklist/<user_id>`          | admin | unblacklist | FR-10 |
| GET    | `/api/admin/bookings`                     | admin | all bookings | FR-08 |
| POST   | `/api/admin/seats`                        | admin | create seat | - |
| POST   | `/api/admin/bookings/<id>/flag-empty`     | admin | flag empty-seat occupation during patrol | **FR-11** |
| GET    | `/api/admin/users`                        | admin | list users | - |

### Unified error format

All non-2xx responses return:

```json
{ "error": "human readable", "code": "AUTH_001", "details": [...] }
```

Codes: `AUTH_001` (401), `PERM_001` (403), `PARAM_001` (400), `BUS_001` (409), `RES_001` (404), `SYS_001` (500).

---

## Tests

```bash
pytest tests/ -v --cov=app --cov-report=term-missing
```

15 AI-generated cases covering FR-01..FR-11, all four error code groups, and unified error format. Coverage report can also be exported with `--cov-report=html`.

---

## CI/CD pipeline

`.github/workflows/ci.yml` (extends the Week 6 lab pattern):

| Job | Steps | Failure behaviour |
|-----|-------|-------------------|
| `test` | flake8 (E9/F-class only) → pytest with coverage | block stage 2 |
| `build` | `needs: test` → `docker build` → tag verify | only runs when `test` is green |

Artefacts: coverage XML uploaded on every run.

---

## Deployment

Two-target split, mirroring the Week 6 Practical:

| Target | What is deployed | Reason |
|--------|------------------|--------|
| **GitHub Pages** | static landing snapshot of the SPA | matches Practical 3 (Pages) workflow |
| **Render** (free tier) | Flask backend (this entire directory, via `Dockerfile`) | Pages cannot host Python backends |

Render auto-deploys on push to `main`. Production overrides:

| Env var | Purpose |
|---------|---------|
| `SECRET_KEY` | replace dev default for token signing |
| `FLASK_HOST` / `FLASK_PORT` | bind config (defaults `0.0.0.0:5000`) |
| `TOKEN_MAX_AGE` | token validity in seconds (default `43200` = 12h) |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | seed admin account |

Limitations: SQLite resets on container restart; production migration would move to PostgreSQL.

---

## Reproducibility

Re-running `../Task1/DTS114_CW_Task1.ipynb` (Restart & Run All) regenerates this directory from scratch. AI-generation audit logs are at `docs/image_generation_audit.json` and `docs/test_generation_audit.json`.

---

## Methodology

**Hybrid AI-DLC** — AI is the first-pass author, the human is the loss function. The notebook applies an audit gate at every SDLC phase (requirements → design → implementation → verification). See `../Report.pdf` for the full reflective report.
