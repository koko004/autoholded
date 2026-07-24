# Plan de Implementación: Fichador Automático Holded

## 📋 Resumen del Proyecto

Aplicación web para automatizar el fichaje en Holded mediante Playwright, con interfaz FastAPI, ejecución programada automática y despliegue en Docker.

**Objetivo:** Automatizar el proceso de fichaje de entrada/salida en Holded según horarios configurables, con soporte para pausas, calendario laboral y notificaciones.

---

## 🏗️ Arquitectura Técnica

### Stack Tecnológico
- **Backend:** FastAPI (Python 3.11+)
- **Automatización:** Playwright (headless Chromium)
- **Scheduler:** APScheduler (BackgroundScheduler)
- **Base de datos:** SQLite + SQLAlchemy ORM
- **Frontend:** HTML/CSS/JavaScript (Jinja2 templates o React ligero)
- **Contenedorización:** Docker + docker-compose
- **Notificaciones:** Email SMTP / Webhook opcional

### Componentes Principales
1. **Fichador Engine** - Módulo Playwright para automatizar Holded
2. **Scheduler Service** - Programación de tareas de fichaje
3. **API REST** - Endpoints para configuración y control
4. **Web UI** - Interfaz de configuración y monitoreo
5. **Data Layer** - Persistencia de configuración y logs

---

## 🗄️ Esquema de Base de Datos

### Tablas Principales

```sql
-- Configuración de usuario
CREATE TABLE user_config (
    id INTEGER PRIMARY KEY,
    holded_email TEXT NOT NULL,
    holded_password TEXT NOT NULL,  -- Cifrado
    timezone TEXT DEFAULT 'Europe/Madrid',
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- Horarios de trabajo
CREATE TABLE work_schedule (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,              -- Ej: "Horario normal", "Turno de mañana"
    entry_time TIME NOT NULL,        -- Hora de entrada
    exit_time TIME NOT NULL,         -- Hora de salida
    pause_start TIME,                -- Inicio pausa
    pause_end TIME,                  -- Fin pausa
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP
);

-- Días laborables
CREATE TABLE work_days (
    id INTEGER PRIMARY KEY,
    schedule_id INTEGER REFERENCES work_schedule(id),
    day_of_week INTEGER NOT NULL,   -- 0=Lunes, 6=Domingo
    is_workday BOOLEAN DEFAULT TRUE
);

-- Calendario laboral (festivos y vacaciones)
CREATE TABLE calendar_events (
    id INTEGER PRIMARY KEY,
    event_date DATE NOT NULL,
    event_type TEXT NOT NULL,        -- 'holiday', 'vacation', 'special_schedule'
    schedule_id INTEGER REFERENCES work_schedule(id),  -- Para días especiales
    description TEXT,
    created_at TIMESTAMP
);

-- Registro de fichajes
CREATE TABLE attendance_log (
    id INTEGER PRIMARY KEY,
    date DATE NOT NULL,
    entry_time TIMESTAMP,
    exit_time TIMESTAMP,
    pause_minutes INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',   -- pending, completed, error
    notes TEXT,
    created_at TIMESTAMP
);

-- Configuración de notificaciones
CREATE TABLE notification_config (
    id INTEGER PRIMARY KEY,
    email_enabled BOOLEAN DEFAULT TRUE,
    email_recipients TEXT,           -- JSON array de emails
    webhook_enabled BOOLEAN DEFAULT FALSE,
    webhook_url TEXT,
    notify_on_success BOOLEAN DEFAULT TRUE,
    notify_on_error BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP
);

-- Logs del sistema
CREATE TABLE system_logs (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    level TEXT NOT NULL,             -- info, warning, error
    module TEXT NOT NULL,            -- scheduler, fichador, api
    message TEXT NOT NULL,
    details TEXT                     -- JSON adicional
);
```

---

## 🔄 Flujo de Trabajo Principal

### Flujo de Fichaje Automático
```
1. Scheduler dispara tarea a la hora configurada
   ↓
2. Verificar si es día laborable (no festivo/vacaciones)
   ↓
3. Instanciar Playwright (headless Chromium)
   ↓
4. Navegar a https://app.holded.com/myzone
   ↓
5. Realizar login con credenciales guardadas
   ↓
6. Navegar a sección "Control horario"
   ↓
7. Hacer clic en "Añadir fichaje"
   ↓
8. Configurar fecha (rango de fechas)
   ↓
9. Seleccionar ubicación (Oficina/Remoto/Sin definir)
   ↓
10. Establecer hora entrada/salida
    ↓
11. Guardar fichaje (clic "Aceptar")
    ↓
12. Registrar resultado en attendance_log
    ↓
13. Enviar notificación si está habilitada
    ↓
14. Cerrar navegador
```

---

## 📡 Endpoints API

### Autenticación y Configuración
```
POST   /api/auth/login          - Login y guardar credenciales
GET    /api/config              - Obtener configuración actual
PUT    /api/config              - Actualizar configuración
```

### Horarios
```
GET    /api/schedules           - Listar horarios
POST   /api/schedules           - Crear horario
PUT    /api/schedules/{id}      - Actualizar horario
DELETE /api/schedules/{id}      - Eliminar horario
GET    /api/schedules/{id}/days - Obtener días del horario
PUT    /api/schedules/{id}/days - Actualizar días del horario
```

### Calendario Laboral
```
GET    /api/calendar            - Listar eventos del calendario
POST   /api/calendar            - Añadir evento (festivo/vacaciones)
DELETE /api/calendar/{id}       - Eliminar evento
GET    /api/calendar/today      - Verificar si hoy es laborable
```

### Fichajes
```
GET    /api/attendance                    - Listar fichajes
GET    /api/attendance/today              - Fichaje de hoy
POST   /api/attendance/manual             - Fichaje manual
GET    /api/attendance/history            - Historial con filtros
GET    /api/attendance/stats              - Estadísticas
```

### Scheduler y Control
```
POST   /api/scheduler/start     - Iniciar scheduler
POST   /api/scheduler/stop      - Detener scheduler
GET    /api/scheduler/status    - Estado del scheduler
POST   /api/scheduler/force     - Ejecución forzada inmediata
```

### Logs y Monitoreo
```
GET    /api/logs                - Obtener logs del sistema
GET    /api/logs/attendance     - Logs de fichajes
DELETE /api/logs/clean          - Limpiar logs antiguos
```

---

## 🖥️ Interfaz Web (FastAPI + Templates)

### Páginas Principales

1. **Dashboard (`/`)**
   - Estado del scheduler (activo/inactivo)
   - Próximo fichaje programado
   - Resumen del día (horas trabajadas)
   - Últimos fichajes registrados
   - Alertas y notificaciones

2. **Configuración (`/config`)**
   - Credenciales Holded (email/contraseña)
   - Zona horaria
   - Configuración de notificaciones

3. **Horarios (`/schedules`)**
   - Lista de horarios configurados
   - Formulario crear/editar horario
   - Configuración de pausas
   - Selección de días laborables

4. **Calendario (`/calendar`)**
   - Vista mensual del calendario laboral
   - Marcar festivos y vacaciones
   - Importar/exportar calendario

5. **Historial (`/attendance`)**
   - Tabla de fichajes con filtros
   - Estadísticas (horas semanales/mensuales)
   - Exportar a CSV/Excel

6. **Logs (`/logs`)**
   - Log del sistema en tiempo real
   - Filtrar por nivel/módulo/fecha
   - Limpiar logs antiguos

---

## 🐳 Configuración Docker

### Estructura del Proyecto
```
fichador-holded/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app
│   ├── config.py               # Settings
│   ├── database.py             # SQLAlchemy setup
│   ├── models/                 # Modelos DB
│   ├── schemas/                # Pydantic schemas
│   ├── routers/                # API routes
│   ├── services/               # Business logic
│   │   ├── fichador.py         # Playwright engine
│   │   ├── scheduler.py        # APScheduler
│   │   └── notifications.py    # Email/Webhook
│   ├── templates/              # Jinja2 templates
│   └── static/                 # CSS/JS/images
├── tests/
├── docs/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
└── README.md
```

### Docker Compose
```yaml
version: '3.8'

services:
  fichador:
    build: .
    container_name: fichador-holded
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data          # SQLite DB
      - ./logs:/app/logs          # Logs
      - ./config:/app/config      # Configuración
    environment:
      - DATABASE_URL=sqlite:///data/fichador.db
      - TZ=Europe/Madrid
    depends_on:
      - chromium

  chromium:
    image: browserless/chrome
    container_name: fichador-chromium
    restart: unless-stopped
    ports:
      - "3000:3000"
    environment:
      - CONNECTION_TIMEOUT=300
      - MAX_CONCURRENT_SESSIONS=1
```

---

## ⏰ Programación de Tareas

### Configuración del Scheduler
- **Ejecución:** Diaria a la hora de entrada y salida configurada
- **Verificación previa:** Comprobar si es día laborable
- **Reintentos:** Máximo 3 intentos en caso de error
- **Timeout:** 5 minutos máximo por operación de fichaje
- **Logs:** Registro detallado de cada ejecución

### Ejemplo de Configuración
```python
scheduler.add_job(
    fichar_entrada,
    CronTrigger(hour=9, minute=0, day_of_week='mon-fri'),
    id='fichaje_entrada',
    misfire_grace_time=300
)

scheduler.add_job(
    fichar_salida,
    CronTrigger(hour=17, minute=0, day_of_week='mon-fri'),
    id='fichaje_salida',
    misfire_grace_time=300
)
```

---

## 🛡️ Seguridad

1. **Credenciales:** Cifrado AES-256 para contraseña Holded
2. **HTTPS:** Configurar certificado SSL/TLS
3. **Autenticación:** API key o JWT para endpoints
4. **Rate limiting:** Prevenir abuso de la API
5. **Logs sensibles:** Nunca logear contraseñas

---

## 📊 Características Adicionales

### Notificaciones
- Email al completar fichaje
- Alerta en caso de error
- Recordatorio si no se fichó

### Estadísticas
- Horas trabajadas por semana/mes
- Días de ausencia
- Balance de horas

### Exportación
- CSV de fichajes
- Informes mensuales
- Integración con calendario (iCal)

---

## 🚀 Pasos de Implementación

### Fase 1: Fundamentos (Días 1-2)
1. Crear estructura del proyecto
2. Configurar FastAPI base
3. Implementar modelos SQLAlchemy
4. Configurar Docker básico

### Fase 2: Fichador Playwright (Días 3-4)
1. Implementar login automatizado
2. Implementar navegación a Control horario
3. Implementar creación de fichaje
4. Manejo de errores y reintentos

### Fase 3: Scheduler (Día 5)
1. Integrar APScheduler
2. Configurar tareas cron
3. Implementar lógica de días laborables

### Fase 4: API y Web UI (Días 6-8)
1. Implementar todos los endpoints
2. Crear interfaz web con templates
3. Formularios de configuración
4. Dashboard de monitoreo

### Fase 5: Extras (Días 9-10)
1. Sistema de notificaciones
2. Estadísticas y reportes
3. Exportación CSV
4. Documentación y tests

---

## ⚠️ Riesgos y Mitigaciones

| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| Cambios en UI de Holded | Alto | Selectores robustos, monitoreo, actualizaciones rápidas |
| Bloqueo por intentos fallidos | Alto | Rate limiting, reintentos con backoff |
| Credenciales comprometidas | Crítico | Cifrado, acceso restringido, rotación |
| Fallo de scheduler | Medio | Persistencia de tareas, watchdog |
| Problemas de red | Medio | Reintentos, timeout configurables |

---

## 📝 Notas Importantes

1. **Legalidad:** Verificar que el uso cumpla con la normativa laboral
2. **Transparencia:** Considerar informar a recursos humanos
3. **Auditoría:** Mantener logs completos para auditorías
4. **Mantenimiento:** Actualizar selectores si Holded cambia su UI
