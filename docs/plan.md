# Plan de Implementación: Fichador Automático Holded

## Resumen del Proyecto

Aplicación web para automatizar el fichaje en Holded mediante Playwright, con interfaz FastAPI, ejecución programada automática y despliegue en Docker. Incluye bot de Telegram para control remoto.

**Objetivo:** Automatizar el proceso de fichaje en Holded según horarios configurables, con soporte para pausas, fichaje manual, corrección de fichajes, notificaciones y control remoto vía Telegram.

**Versión actual:** v1.4.3
**Interfaz:** Español | **Timezone:** Europe/Madrid

---

## Arquitectura Técnica

### Stack Tecnológico

| Componente | Tecnología |
|------------|------------|
| Backend | Python 3.11+ / FastAPI 0.104.1 |
| Automatización | Playwright 1.40.0 (Chromium embebido) |
| Scheduler | APScheduler 3.10.4 (AsyncIOScheduler, cron triggers) |
| Bot | python-telegram-bot 20.7 (polling) |
| Templates | Jinja2 + vanilla JavaScript |
| Validación | Pydantic v2 2.5.2 |
| Persistencia | Archivos JSON (sin base de datos relacional) |
| Contenedor | Docker + Docker Compose (1 servicio) |

### Componentes Principales

1. **Fichador Engine** — Motor Playwright que automatiza Holded (login, 2FA, live tracking, fichaje manual, corrección)
2. **Scheduler Service** — Programación de tareas con APScheduler (cron triggers por bloque de trabajo)
3. **Telegram Bot** — Control remoto con comandos + envío de screenshots automáticas
4. **API REST** — ~30 endpoints para configuración y control
5. **Web UI** — 7 páginas: Dashboard, Configuración, Horarios, Calendario, Historial, Debug, Logs
6. **Data Layer** — Persistencia en archivos JSON vía `storage.py`

---

## Persistencia de Datos

Toda la persistencia se realiza en archivos JSON dentro de `data/`:

```
data/
├── schedules.json      # Horarios de trabajo (bloques, ubicación, días laborables)
├── config.json         # Configuración (credenciales Holded, Telegram, notificaciones)
├── attendance.json     # Registro de fichajes (upsert por fecha)
├── calendar.json       # Eventos del calendario laboral
├── cookies/            # Sesiones Holded persistidas
├── debug/              # Screenshots de Playwright (paso a paso)
├── *.png               # Screenshots de debug (última operación)
```

**Nota:** Existen modelos SQLAlchemy en `app/models/` pero son código muerto. No se usa base de datos relacional.

---

## Flujo de Trabajo Principal

### Flujo de Fichaje Automático (Scheduler)

El scheduler usa **live tracking** (botones Play/Pause/Stop), NO el formulario "Añadir fichaje".

```
1. Scheduler dispara job a la hora configurada (cron trigger)
   ↓
2. Verificar si es día laborable (L-V por defecto)
   ↓
3. Verificar sesión válida (cookies persistidas)
   ↓
4. Instanciar Playwright (Chromium embebido, headless configurable)
   ↓
5. Navegar a https://app.holded.com/myzone/time-tracking
   ↓
6. Cerrar panel de Intercom si está abierto
   ↓
7. Ejecutar acción según el job:
   - start → clic en ▶ Play (iniciar/reanudar fichaje)
   - pause → clic en ⏸ Pause (pausar fichaje)
   - stop  → clic en ⏹ Stop (finalizar fichaje)
   ↓
8. Guardar registro en attendance.json (upsert por fecha)
   ↓
9. Enviar screenshots a Telegram (si está configurado)
   ↓
10. Cerrar navegador
```

### Mapeo de jobs por bloque de trabajo

Para un horario con bloques `[{entry: "10:00", exit: "13:00", type: "Trabajado"}, {entry: "15:00", exit: "19:00", type: "Trabajado"}]`:

| Hora | Job | Acción |
|------|-----|--------|
| 10:00 | `schedule_X_start` | `start_live_tracking` (▶ Play) |
| 13:00 | `schedule_X_block0_pause` | `pause_live_tracking` (⏸ Pause) |
| 15:00 | `schedule_X_block1_resume` | `start_live_tracking` (▶ Play) |
| 19:00 | `schedule_X_stop` | `stop_live_tracking` (⏹ Stop) |

### Fichaje Manual

```
1. Usuario introduce fecha en Dashboard o envía /fichar en Telegram
   ↓
2. Coge horario activo de schedules.json
   ↓
3. Playwright → Control horario → "Añadir fichaje"
   ↓
4. Rellena fecha, ubicación, y filas de horario (entry/exit por bloque)
   ↓
5. Clic en "Aceptar"
   ↓
6. Guarda en attendance.json
```

### Corregir Fichaje

```
1. Usuario pulsa "Corregir Fichaje de Hoy" o envía /corregir en Telegram
   ↓
2. Coge horario activo de schedules.json
   ↓
3. Playwright → /myzone/time-tracking → cierra Intercom
   ↓
4. Clic en la fila del día (data-id="YYYY-MM-DD")
   ↓
5. Clic en "Editar fichajes"
   ↓
6. Selecciona ubicación, rellena bloques de trabajo
   ↓
7. Doble clic en "Guardar"
```

### Control en Tiempo Real (Dashboard)

Los botones del Dashboard ejecutan la misma lógica que el scheduler:
- **Fichar Ahora** → `start_live_tracking`
- **Iniciar Pausa** → `pause_live_tracking`
- **Finalizar Pausa** → `start_live_tracking`
- **Finalizar Fichaje** → `stop_live_tracking`

---

## Endpoints API

### Autenticación
```
POST   /api/auth/login              - Login con email/password (2FA)
POST   /api/auth/2fa                - Verificar código 2FA
POST   /api/auth/check-session      - Verificar sesión Holded
GET    /api/auth/session-info       - Info de sesión (TTL, email)
POST   /api/auth/logout             - Cerrar sesión
```

### Configuración
```
GET    /api/config                  - Obtener configuración
PUT    /api/config                  - Actualizar configuración
GET    /api/config/headless         - Estado modo headless
POST   /api/config/headless         - Cambiar modo headless
```

### Horarios
```
GET    /api/schedules               - Listar horarios
POST   /api/schedules               - Crear horario
PUT    /api/schedules/{id}          - Actualizar horario
DELETE /api/schedules/{id}          - Eliminar horario
```

### Fichajes
```
GET    /api/attendance              - Listar fichajes
DELETE /api/attendance/{id}         - Eliminar fichaje
GET    /api/attendance/today        - Estado de hoy
POST   /api/attendance/manual-fichaje  - Fichaje manual (formulario Añadir fichaje)
POST   /api/attendance/corregir-fichaje - Corregir fichaje de hoy (editar existente)
POST   /api/attendance/modify-fichaje   - Modificar fichaje existente
```

### Scheduler y Control en Tiempo Real
```
POST   /api/scheduler/start         - Iniciar scheduler
POST   /api/scheduler/stop          - Detener scheduler
GET    /api/scheduler/status        - Estado del scheduler
POST   /api/scheduler/force         - Ejecución forzada (play/pause/stop/exit)
```

### Telegram Bot
```
GET    /api/telegram/config         - Config Telegram (token enmascarado)
PUT    /api/telegram/config         - Actualizar config Telegram
POST   /api/telegram/test           - Probar conexión Telegram
GET    /api/telegram/status         - Estado del bot
```

### Debug y Logs
```
GET    /api/debug/steps             - Pasos de debug (última operación)
GET    /api/debug/screenshot/{f}    - Captura individual
GET    /api/logs                    - Logs del sistema (SSE streaming)
DELETE /api/logs                    - Limpiar logs
```

### Calendario
```
GET    /api/calendar                - Listar eventos
POST   /api/calendar                - Crear evento
DELETE /api/calendar/{id}           - Eliminar evento
```

### Health Check
```
GET    /health                      - Health check
```

---

## Interfaz Web (FastAPI + Jinja2)

### Páginas

1. **Dashboard (`/`)** — Estado del scheduler, estado de hoy, botones de live tracking, fichaje manual, corrección de fichaje, tabla de últimos fichajes
2. **Configuración (`/config`)** — Login 2FA Holded, sesión activa con TTL, bot de Telegram, notificaciones por email
3. **Horarios (`/schedules`)** — CRUD de horarios con bloques de trabajo (Trabajado/Pausa), ubicación, días laborables
4. **Calendario (`/calendar`)** — Vista de eventos laborales
5. **Historial (`/attendance`)** — Tabla de fichajes con filtros, modificar fichaje existente, exportar CSV
6. **Debug (`/debug`)** — Capturas de Playwright paso a paso (ordenadas del más reciente al más antiguo), auto-refresh
7. **Logs (`/logs`)** — Logs del sistema en tiempo real via SSE

---

## Bot de Telegram

### Comandos

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

### Modos de screenshots
- `all` — Todas las capturas de cada acción (4-6 imágenes)
- `last` — Solo la última captura (resultado final)
- `summary` — Última captura + mensaje de resumen

### Autocompletado
Los comandos se registran automáticamente con `set_my_commands` al iniciar el bot.

---

## Estructura del Proyecto

```
fichador-holded/
├── app/
│   ├── main.py              - Entry point FastAPI + lifecycle (auto-start scheduler y bot)
│   ├── config.py            - Pydantic Settings (.env vars)
│   ├── database.py          - SQLAlchemy async engine (UNUSED)
│   ├── models/
│   │   └── __init__.py      - SQLAlchemy ORM models (7 tablas, UNUSED)
│   ├── schemas/
│   │   └── __init__.py      - Pydantic request/response schemas
│   ├── routers/
│   │   ├── api.py           - REST API (~30 endpoints)
│   │   └── web.py           - Rutas HTML (7 páginas)
│   ├── services/
│   │   ├── fichador.py      - Motor Playwright (~1900 líneas, core de la app)
│   │   ├── scheduler.py     - APScheduler con cron triggers
│   │   ├── storage.py       - Persistencia en archivos JSON
│   │   ├── telegram_bot.py  - Bot de Telegram (polling, comandos, screenshots)
│   │   └── notifications.py - Email SMTP + webhooks
│   ├── templates/           - Templates Jinja2 (7 páginas)
│   └── static/
│       ├── css/style.css    - Estilos + responsive móvil
│       ├── js/main.js       - Funciones JS compartidas
│       └── img/             - Logo, favicon
├── data/                    - Runtime: JSON storage, cookies, screenshots, debug
├── tests/                   - Tests (vacío)
├── docs/
│   └── plan.md              - Este archivo
├── *.ts                     - Scripts Playwright grabados (referencia, NO se ejecutan)
├── docker-compose.yml       - Desarrollo (build local)
├── docker-compose.prod.yml  - Producción (imagen Docker Hub + .env)
├── docker-compose.nodotenv.yml - Producción sin .env (variables inline)
├── Dockerfile               - Python 3.11-slim + Chromium + dependencias Playwright
├── entrypoint.sh            - Xvfb + uvicorn
├── requirements.txt         - 15 dependencias
├── .env                     - Credenciales reales (gitignored)
├── .env.example             - Placeholders seguros
├── .gitignore               - Excluye archivos sensibles
└── README.md                - Documentación del proyecto
```

---

## Configuración Docker

### Desarrollo (build local)
```bash
docker compose up --build -d
```

### Producción (imagen pre-compilada)
```bash
# Con .env
docker compose -f docker-compose.prod.yml up -d

# Sin .env (variables inline)
docker compose -f docker-compose.nodotenv.yml up -d
```

### Servicios

| Servicio | Descripción |
|----------|-------------|
| `fichador` | Aplicación completa (FastAPI + Chromium embebido + Xvfb) |

**Puerto:** 8002:8000
**Volumen:** `./data:/app/data`
**SHM:** 2gb (necesario para Chromium)
**Variables clave:** `HEADLESS=false`, `DISPLAY=:99`, `TZ=Europe/Madrid`

---

## Selección de Selectores Playwright

Estrategia de selección multi-fallback para resistir cambios en la UI de Holded:

| Elemento | Selector principal | Fallback |
|----------|-------------------|----------|
| Play button | `button:has(svg[aria-label="Icon-play"])` | `get_by_role("button", name="Play")` |
| Pause button | `button:has(svg[aria-label="Icon-pause"])` | `get_by_role("button", name="Pause")` |
| Stop button | `button:has(svg[aria-label="Icon-stop"])` | `get_by_role("button", name="Stop")` |
| Intercom close | `document.querySelector('[data-testid="close-button"]')` | CSS hide como fallback |
| Fichaje row | `[data-id="YYYY-MM-DD"]` (MUI DataGrid) | `get_by_text("Lun 27")` |
| Editar fichajes | `get_by_role("button", name="Editar fichajes")` | Text/role fallbacks |
| Ubicación | `get_by_role("combobox", name="Ubicación")` | Iteración por contenido |

---

## Funcionalidades Implementadas (v1.4.3)

### Core
- Login automatizado con 2FA interactivo (asyncio.Event)
- Live tracking: Play, Pause, Stop
- Fichaje manual con formulario "Añadir fichaje"
- Corrección de fichaje existente ("Editar fichajes")
- Selectores robustos con multi-fallback
- Auto-cierre del panel de Intercom
- Detección de errores Holded (MUI Snackbar), ignorando toasts de éxito

### Scheduler
- APScheduler AsyncIOScheduler con cron triggers
- Jobs por bloque de trabajo (start/pause/resume/stop)
- Verificación de días laborables
- Auto-start al iniciar la aplicación
- Persistencia de estado en memoria

### Telegram Bot
- 11 comandos con autocompletado (set_my_commands)
- Screenshots automáticas post-acción (3 modos: all/last/summary)
- Mensaje instantáneo antes de cada acción
- Modo polling (sin webhook)

### Web UI
- 7 páginas con diseño responsive (móvil + escritorio)
- Dashboard con control en tiempo real
- Debug con capturas de Playwright paso a paso (orden invertido: más reciente arriba)
- Logs en tiempo real via SSE
- Configuración de Telegram integrada

### Datos
- Persistencia JSON (upsert por fecha, sin duplicados)
- Attendance con campos inteligentes por tipo de acción
- Sesión Holded persistida (cookies)
- Email del usuario visible en Config (desde .env como fallback)

---

## Pasos de Implementación (Completados)

### Fase 1: Fundamentos ✅
- Estructura del proyecto
- FastAPI base con lifespan
- Modelos Pydantic (schemas)
- Docker básico con Chromium embebido

### Fase 2: Fichador Playwright ✅
- Login automatizado con 2FA
- Navegación a Control horario
- Live tracking (Play/Pause/Stop)
- Fichaje manual ("Añadir fichaje")
- Corrección de fichaje ("Editar fichajes")
- Manejo de errores y selectores robustos

### Fase 3: Scheduler ✅
- APScheduler AsyncIOScheduler
- Cron triggers por bloque de trabajo
- Lógica de días laborables
- Auto-start al iniciar la app

### Fase 4: API y Web UI ✅
- ~30 endpoints REST
- 7 páginas con templates Jinja2
- Responsive móvil
- Dashboard, Config, Horarios, Calendario, Historial, Debug, Logs

### Fase 5: Extras ✅
- Bot de Telegram (11 comandos, screenshots, autocompletado)
- Notificaciones (email + webhook)
- Persistencia JSON con upsert
- Debug screenshots paso a paso

---

## Riesgos y Mitigaciones

| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| Cambios en UI de Holded | Alto | Selectores multi-fallback (aria-label, role, text), screenshots en cada paso |
| Sesión expirada | Alto | Detección automática, notificación Telegram, re-login manual |
| Bloqueo por intentos fallidos | Medio | Un solo intento por acción, sin reintentos automáticos |
| Fallo de scheduler | Medio | Auto-start al reiniciar, estado en memoria |
| Problemas de red | Medio | Timeout configurable (60s), cierre seguro de navegador |

---

## Notas Importantes

1. **Legalidad:** Verificar que el uso cumpla con la normativa laboral
2. **Código muerto:** `app/models/`, `app/database.py` y dependencias SQLAlchemy/aiosqlite no se usan (persistencia es JSON)
3. **Seguridad:** Las credenciales están en `.env` (gitignored). Los endpoints API no tienen autenticación propia
4. **Docker:** La imagen en Docker Hub debe actualizarse manualmente con `docker push` para cada tag
