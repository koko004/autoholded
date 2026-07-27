# Autoholded 

<img width="1920" height="1576" alt="image" src="https://github.com/user-attachments/assets/16c3e60b-f24d-4b4e-95e4-7975978dd76f" />

<br>

Sistema automatizado de fichaje para [Holded ERP](https://www.holded.com/) usando Playwright. Dashboard web para configuración, monitorización y control manual. Bot de Telegram para control remoto.

**Interfaz en español** | **Timezone: Europe/Madrid** | **v1.4.3**

## Características

- **Fichaje automático** por horarios configurables (cron scheduler)
- **Fichaje manual** con formulario integrado en Holded
- **Corregir fichaje** — editar el fichaje del día con el horario activo desde un solo clic
- **Control en tiempo real**: iniciar, pausar y finalizar fichaje desde la web
- **Bot de Telegram**: control remoto con comandos + envío de screenshots automáticas
- **2FA interactivo**: soporte para autenticación de dos factores
- **Debug mode**: capturas de pantalla en cada paso de Playwright, accesibles desde `/debug`
- **Historial de fichajes**: registro local con upsert por fecha, eliminar registros
- **Notificaciones** por email y webhook
- **Responsive**: diseño adaptable a móvil y escritorio
- **Docker ready**: despliegue con un solo comando

## Tech Stack

| Componente | Tecnología |
|------------|------------|
| Backend | Python 3.11+ / FastAPI 0.104.1 |
| Automatización | Playwright 1.40.0 (Chromium embebido) |
| Scheduler | APScheduler 3.10.4 (AsyncIOScheduler, cron triggers) |
| Bot | python-telegram-bot 20.7 (polling) |
| Templates | Jinja2 + vanilla JavaScript |
| Validación | Pydantic v2 2.5.2 |
| Persistencia | Archivos JSON (sin base de datos relacional) |
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

### Producción (imagen pre-compilada)

```bash
# Con .env
docker compose -f docker-compose.prod.yml up -d

# Sin .env (variables inline)
docker compose -f docker-compose.nodotenv.yml up -d
```

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
| `/help` | Lista de comandos |
| `/status` | Estado del scheduler y fichaje de hoy |
| `/play` | Iniciar fichaje (live tracking) |
| `/pause` | Pausar fichaje |
| `/stop` | Finalizar fichaje |
| `/fichar` | Fichaje manual (pide fecha en formato DD/MM/YYYY) |
| `/corregir` | Corregir fichaje de hoy con horario activo |
| `/start_scheduler` | Iniciar scheduler |
| `/stop_scheduler` | Detener scheduler |
| `/screenshots` | Cambiar modo de capturas (all/last/summary) |

**Modos de screenshots:**
- `all` — Todas las capturas de cada acción (4-6 imágenes)
- `last` — Solo la última captura (resultado final)
- `summary` — Última captura + mensaje de resumen

Los comandos se registran automáticamente con `set_my_commands` al iniciar el bot para autocompletado.

### Horarios

Los horarios se configuran desde la web (`/schedules`). Cada horario define:

- **Bloques de trabajo** con tipo (Trabajado / Pausa)
- **Ubicación** (ej: "REAL FEDERACION DE FUTBOL DEL")
- **Días laborables** (L-V)

## Páginas

| Ruta | Descripción |
|------|-------------|
| `/` | Dashboard — estado actual del fichaje, control en tiempo real, fichaje manual, corrección |
| `/config` | Configuración — login 2FA, sesión activa con TTL, Telegram, notificaciones |
| `/schedules` | Horarios — CRUD de horarios con bloques de trabajo |
| `/attendance` | Historial — registros de fichajes con filtros, modificar fichaje, exportar CSV |
| `/calendar` | Calendario — vista de eventos laborales |
| `/debug` | Debug — capturas de Playwright paso a paso (orden invertido: más reciente arriba) |
| `/logs` | Logs — logs del sistema en tiempo real via SSE |

## Endpoints API

### Autenticación
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/api/auth/login` | Login con email/password (2FA) |
| POST | `/api/auth/2fa` | Verificar código 2FA |
| POST | `/api/auth/check-session` | Verificar sesión Holded |
| GET | `/api/auth/session-info` | Info de sesión (TTL, email) |
| POST | `/api/auth/logout` | Cerrar sesión |

### Configuración
| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/config` | Obtener configuración |
| PUT | `/api/config` | Actualizar configuración |
| GET | `/api/config/headless` | Estado modo headless |
| POST | `/api/config/headless` | Cambiar modo headless |

### Horarios
| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/schedules` | Listar horarios |
| POST | `/api/schedules` | Crear horario |
| PUT | `/api/schedules/{id}` | Actualizar horario |
| DELETE | `/api/schedules/{id}` | Eliminar horario |

### Fichajes
| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/attendance` | Listar fichajes |
| DELETE | `/api/attendance/{id}` | Eliminar fichaje |
| GET | `/api/attendance/today` | Estado de hoy |
| POST | `/api/attendance/manual-fichaje` | Fichaje manual (formulario Añadir fichaje) |
| POST | `/api/attendance/corregir-fichaje` | Corregir fichaje de hoy (editar existente) |
| POST | `/api/attendance/modify-fichaje` | Modificar fichaje existente |

### Scheduler y Control en Tiempo Real
| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/api/scheduler/start` | Iniciar scheduler |
| POST | `/api/scheduler/stop` | Detener scheduler |
| GET | `/api/scheduler/status` | Estado del scheduler |
| POST | `/api/scheduler/force` | Ejecución forzada (play/pause/stop/exit) |

### Telegram Bot
| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/telegram/config` | Config Telegram (token enmascarado) |
| PUT | `/api/telegram/config` | Actualizar config Telegram |
| POST | `/api/telegram/test` | Probar conexión Telegram |
| GET | `/api/telegram/status` | Estado del bot |

### Debug y Logs
| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/debug/steps` | Pasos de debug (última operación) |
| GET | `/api/debug/screenshot/{filename}` | Captura individual |
| GET | `/api/logs` | Logs del sistema (SSE streaming) |
| DELETE | `/api/logs` | Limpiar logs |

### Calendario
| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/calendar` | Listar eventos |
| POST | `/api/calendar` | Crear evento |
| DELETE | `/api/calendar/{id}` | Eliminar evento |

### Health Check
| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/health` | Health check |

## Estructura del proyecto

```
app/
  main.py              - Entry point FastAPI + lifecycle (auto-start scheduler y bot)
  config.py            - Configuración con Pydantic Settings
  database.py          - SQLAlchemy async engine (UNUSED — persistencia es JSON)
  models/
    __init__.py        - SQLAlchemy ORM models (7 tablas, UNUSED)
  schemas/
    __init__.py        - Pydantic request/response schemas
  routers/
    api.py             - REST API (~30 endpoints)
    web.py             - Rutas HTML (7 páginas)
  services/
    fichador.py        - Motor Playwright (~1900 líneas, core de la app)
    scheduler.py       - APScheduler con cron triggers
    storage.py         - Persistencia en archivos JSON
    telegram_bot.py    - Bot de Telegram (polling, comandos, screenshots)
    notifications.py   - Email SMTP + webhooks
  templates/           - Templates Jinja2 (7 páginas)
  static/
    css/style.css      - Estilos + responsive móvil
    js/main.js         - Funciones JS compartidas
    img/               - Logo, favicon
data/                  - Runtime: JSON storage, cookies, screenshots, debug
tests/                 - Tests (vacío)
*.ts                   - Scripts Playwright grabados (referencia, NO se ejecutan)
```

## Docker

| Archivo | Descripción |
|---------|-------------|
| `docker-compose.yml` | Desarrollo (build local) |
| `docker-compose.prod.yml` | Producción (imagen Docker Hub + .env) |
| `docker-compose.nodotenv.yml` | Producción sin .env (variables inline) |

**Puerto:** 8002:8000
**Volumen:** `./data:/app/data`
**SHM:** 2gb (necesario para Chromium)

## Licencia

Proyecto privado — REAL FEDERACION DE FUTBOL DEL
