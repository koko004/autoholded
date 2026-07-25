# Fichador Holded

Sistema automatizado de fichaje para [Holded ERP](https://www.holded.com/) usando Playwright. Dashboard web para configuración, monitorización y control manual.

**Interfaz en español** | **Timezone: Europe/Madrid**

## Características

- **Fichaje automático** por horarios configurables (cron scheduler)
- **Fichaje manual** con formulario integrado en Holded
- **Control en tiempo real**: iniciar, pausar y finalizar fichaje desde la web
- **2FA interactivo**: soporte para autenticación de dos factores
- **Debug mode**: capturas de pantalla en cada paso de Playwright, accesibles desde `/debug`
- **Notificaciones** por email y webhook
- **Docker ready**: despliegue con un solo comando

## Tech Stack

| Componente | Tecnología |
|------------|------------|
| Backend | Python 3.11+ / FastAPI |
| Automatización | Playwright (Chromium) |
| Scheduler | APScheduler (cron triggers) |
| Templates | Jinja2 + vanilla JS |
| Validación | Pydantic v2 |
| Contenedor | Docker + Docker Compose |

## Instalación

### Docker (recomendado)

```bash
git clone https://github.com/koko004/autoholded.git
cd autoholded
cp .env.example .env
# Edita .env con tus credenciales de Holded
docker compose up --build -d
```

La app estará disponible en `http://localhost:8002`

### Manual

```bash
pip install -r requirements.txt
playwright install chromium
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Configuración

Copia `.env.example` a `.env` y configura:

```env
# Credenciales Holded
HOLDED_EMAIL=tu@email.com
HOLDED_PASSWORD=tu_contraseña

# Modo visible (para debug con screenshots)
HEADLESS=false

# Timezone
TZ=Europe/Madrid
```

### Horarios

Los horarios se configuran desde la web (`/schedules`). Cada horario define:

- **Bloques de trabajo** con tipo (Trabajado / Pausa)
- **Ubicación** (ej: "ARCO C.B.")
- **Días laborables** (L-V)

## Endpoints API

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/api/scheduler/force` | Forzar fichaje (entry/pause_start/pause_end/exit) |
| POST | `/api/attendance/manual-fichaje` | Fichaje manual con formulario |
| GET | `/api/debug/steps` | Pasos de debug del último fichaje |
| GET | `/api/schedules` | Listar horarios |
| GET | `/` | Dashboard |
| GET | `/debug` | Debug screenshots (auto-refresh 3s) |
| GET | `/config` | Configuración |
| GET | `/schedules` | Gestión de horarios |

## Páginas

- **Dashboard** (`/`) - Estado actual del fichaje
- **Configuración** (`/config`) - Login 2FA, modo headless
- **Horarios** (`/schedules`) - CRUD de horarios
- **Debug** (`/debug`) - Capturas de Playwright paso a paso
- **Logs** (`/logs`) - Logs del sistema
- **Attendance** (`/attendance`) - Historial de fichajes
- **Calendar** (`/calendar`) - Vista calendario

## Estructura del proyecto

```
app/
  main.py              - Entry point FastAPI
  config.py            - Configuración con Pydantic Settings
  routers/
    api.py             - REST API (~25 endpoints)
    web.py             - Rutas HTML (6 páginas)
  services/
    fichador.py        - Motor Playwright (automatización core)
    scheduler.py       - Scheduler cron con APScheduler
    storage.py         - Persistencia en archivos JSON
    notifications.py   - Email SMTP + webhooks
  templates/           - Templates Jinja2
  static/              - CSS, JS, imágenes
data/                  - JSON storage, cookies, screenshots (runtime)
```

## Licencia

Proyecto privado - ARCO C.B.
