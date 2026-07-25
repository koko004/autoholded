# Autoholded

Sistema automatizado de fichaje para [Holded ERP](https://www.holded.com/) usando Playwright. Dashboard web para configuración, monitorización y control manual. Bot de Telegram para control remoto.

**Interfaz en español** | **Timezone: Europe/Madrid**

## Características

- **Fichaje automático** por horarios configurables (cron scheduler)
- **Fichaje manual** con formulario integrado en Holded
- **Control en tiempo real**: iniciar, pausar y finalizar fichaje desde la web
- **Bot de Telegram**: control remoto con comandos + envío de screenshots automáticas
- **2FA interactivo**: soporte para autenticación de dos factores
- **Debug mode**: capturas de pantalla en cada paso de Playwright, accesibles desde `/debug`
- **Historial de fichajes**: registro local con upsert por fecha
- **Notificaciones** por email y webhook
- **Docker ready**: despliegue con un solo comando

## Tech Stack

| Componente | Tecnología |
|------------|------------|
| Backend | Python 3.11+ / FastAPI |
| Automatización | Playwright (Chromium) |
| Scheduler | APScheduler (cron triggers) |
| Bot | python-telegram-bot (polling) |
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

# Bot de Telegram (opcional)
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=-1001234567890
TELEGRAM_ENABLED=true
TELEGRAM_SCREENSHOT_MODE=last
```

### Bot de Telegram

Controla el fichaje desde Telegram con estos comandos:

| Comando | Descripción |
|---------|-------------|
| `/start` | Bienvenida y lista de comandos |
| `/status` | Estado del scheduler y fichaje de hoy |
| `/play` | Iniciar fichaje |
| `/pause` | Pausar fichaje |
| `/stop` | Finalizar fichaje |
| `/fichar` | Fichaje manual (pide fecha) |
| `/start_scheduler` | Iniciar scheduler |
| `/stop_scheduler` | Detener scheduler |
| `/screenshots` | Ver/cambiar modo de capturas |
| `/help` | Lista de comandos |

**Modos de screenshots:**
- `all` — Todas las capturas de cada acción (4-6 imágenes)
- `last` — Solo la última captura (resultado final)
- `summary` — Última captura + mensaje de resumen

Configuración: desde la página `/config` o con `/screenshots all|last|summary` en el chat.

### Horarios

Los horarios se configuran desde la web (`/schedules`). Cada horario define:

- **Bloques de trabajo** con tipo (Trabajado / Pausa)
- **Ubicación** (ej: "ARCO C.B.")
- **Días laborables** (L-V)

## Páginas

| Ruta | Descripción |
|------|-------------|
| `/` | Dashboard — estado actual del fichaje |
| `/config` | Configuración — login 2FA, Telegram, notificaciones |
| `/schedules` | Horarios — CRUD de horarios |
| `/attendance` | Historial — registros de fichajes con filtros |
| `/debug` | Debug — capturas de Playwright paso a paso |
| `/logs` | Logs — logs del sistema en tiempo real |
| `/calendar` | Calendario — vista de eventos |

## Endpoints API

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/api/auth/login` | Login con email/password |
| POST | `/api/auth/2fa` | Verificar código 2FA |
| POST | `/api/auth/check-session` | Verificar sesión Holded |
| GET | `/api/auth/session-info` | Info de sesión (TTL, email) |
| GET | `/api/config` | Obtener configuración |
| PUT | `/api/config` | Actualizar configuración |
| GET | `/api/schedules` | Listar horarios |
| POST | `/api/schedules` | Crear horario |
| PUT | `/api/schedules/{id}` | Actualizar horario |
| DELETE | `/api/schedules/{id}` | Eliminar horario |
| GET | `/api/attendance` | Listar fichajes |
| GET | `/api/attendance/today` | Estado de hoy |
| POST | `/api/attendance/manual-fichaje` | Fichaje manual |
| POST | `/api/attendance/modify-fichaje` | Modificar fichaje |
| POST | `/api/scheduler/force` | Forzar acción |
| GET | `/api/scheduler/status` | Estado del scheduler |
| GET | `/api/debug/steps` | Pasos de debug |
| GET | `/api/debug/screenshot/{filename}` | Captura individual |
| GET | `/api/telegram/config` | Config Telegram |
| PUT | `/api/telegram/config` | Actualizar Telegram |
| POST | `/api/telegram/test` | Probar conexión Telegram |
| GET | `/api/telegram/status` | Estado del bot |

## Estructura del proyecto

```
app/
  main.py              - Entry point FastAPI + lifecycle
  config.py            - Configuración con Pydantic Settings
  routers/
    api.py             - REST API (~25 endpoints)
    web.py             - Rutas HTML (6 páginas)
  services/
    fichador.py        - Motor Playwright (automatización core)
    scheduler.py       - Scheduler cron con APScheduler
    storage.py         - Persistencia en archivos JSON
    telegram_bot.py    - Bot de Telegram (polling, comandos, screenshots)
    notifications.py   - Email SMTP + webhooks
  models/              - SQLAlchemy models (UNUSED — JSON storage)
  schemas/             - Pydantic request/response schemas
  templates/           - Templates Jinja2
  static/              - CSS, JS, imágenes
data/                  - JSON storage, cookies, screenshots (runtime)
tests/                 - Tests (vacío)
```

## Licencia

Proyecto privado — ARCO C.B.
