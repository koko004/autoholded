# AGENTS.md — Fichador Holded

## Project Overview

Automated time clock ("fichaje") system for Holded ERP. Uses Playwright browser automation to clock in/out on `app.holded.com`. Web dashboard for configuration, monitoring, and manual control. Interface in Spanish, timezone `Europe/Madrid`.

## Tech Stack

- **Language:** Python 3.11+
- **Framework:** FastAPI 0.104.1
- **Server:** Uvicorn 0.24.0
- **ORM:** SQLAlchemy 2.0.23 (async, but NOT used — dead code)
- **Database:** JSON files via `storage.py` (despite SQLAlchemy models existing)
- **Browser Automation:** Playwright 1.40.0 (Chromium, async API)
- **Scheduler:** APScheduler 3.10.4 (cron triggers)
- **Validation:** Pydantic v2 2.5.2
- **Templates:** Jinja2 3.1.2 + vanilla JS (no frontend framework)
- **Container:** Docker + Docker Compose (3 services: app, browserless, chrome-vnc)

## Run Commands

| Method | Command |
|--------|---------|
| Docker (recommended) | `docker-compose up --build` |
| Manual | `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload` |
| Health check | `GET http://localhost:8000/health` |

**No lint, test, or build commands are configured.** `tests/` directory exists but is empty.

## Project Structure

```
app/
  main.py              - FastAPI entry point, lifespan, router mounting
  config.py            - Pydantic Settings (.env vars)
  database.py          - SQLAlchemy async engine (UNUSED)
  models/__init__.py   - SQLAlchemy ORM models (7 tables, UNUSED)
  schemas/__init__.py  - Pydantic request/response schemas
  routers/
    api.py             - REST API (~25 endpoints under /api)
    web.py             - HTML page routes (6 pages)
  services/
    fichador.py        - Core Playwright engine (1565 lines, heart of app)
    scheduler.py       - APScheduler cron jobs (340 lines)
    storage.py         - JSON file persistence (actual data layer)
    notifications.py   - Email SMTP + webhook notifications
  templates/           - Jinja2 HTML templates (7 pages)
  static/              - CSS, JS, images
data/                  - Runtime: JSON storage, cookies, screenshots
tests/                 - EMPTY (no tests)
docs/plan.md           - Implementation plan (Spanish)
*.ts files at root     - Recorded Playwright scripts (reference only, NOT executed)
```

## Architecture Notes

- **Hybrid data layer:** SQLAlchemy models exist but are dead code. All persistence is JSON files via `storage.py`. Every API call re-reads from disk.
- **Singleton services:** `fichador`, `scheduler`, `notifications` are module-level instances.
- **2FA flow:** Uses `asyncio.Event`-like coordination between API endpoint and background Playwright task.
- **Playwright selector strategy:** Multi-fallback approach (exact CSS → partial match → ARIA labels) to handle Holded UI changes.

## Critical Issues

1. **Hardcoded credentials** in `.ts` files at project root (email/password in plaintext)
2. **Real session data** committed in `data/cookies/holded_session.json`
3. **No application auth** — all API endpoints are completely open
4. **Dead ORM layer** — SQLAlchemy models exist but are never used
5. **No tests, no linting, no CI/CD**
6. **Bare `except:` clauses** throughout Playwright automation
7. **JSON storage has no concurrency protection**

## Conventions

- Interface and all user-facing text is in Spanish
- Pydantic v2 with `Field` validation (`pattern`, `min_length`)
- Playwright screenshots saved at each step for debugging (`data/*.png`)
- Docker entrypoint starts Xvfb for virtual display
- Notifications are self-referential (sender receives own notifications)

## Key Files

| File | Lines | Purpose |
|------|-------|---------|
| `app/services/fichador.py` | 1565 | Core Playwright automation |
| `app/routers/api.py` | 497 | REST API endpoints |
| `app/services/scheduler.py` | 340 | Cron job scheduler |
| `app/schemas/__init__.py` | 228 | Pydantic schemas |
| `app/services/storage.py` | 166 | JSON file storage |
| `app/templates/dashboard.html` | 478 | Dashboard (inline JS) |
| `app/templates/schedules.html` | 442 | Schedules page |
| `app/templates/config.html` | 440 | Config page |
| `app/services/notifications.py` | 127 | Email/webhook notifications |
| `app/models/__init__.py` | 100 | SQLAlchemy models (UNUSED) |
| `app/config.py` | 61 | App configuration |
| `app/database.py` | 46 | Database setup (UNUSED) |
| `app/main.py` | 73 | App entry point |
