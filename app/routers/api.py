"""API router for REST endpoints."""
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from typing import List, Optional
from datetime import date, datetime, time
from pydantic import BaseModel
import asyncio
import logging

from app.schemas import (
    UserConfigCreate, UserConfigResponse, UserConfigUpdate,
    WorkScheduleCreate, WorkScheduleResponse, WorkScheduleUpdate, WorkBlock,
    CalendarEventCreate, CalendarEventResponse,
    AttendanceLogResponse, AttendanceLogCreate,
    MessageResponse, ErrorResponse, SchedulerStatus,
    ForceFichajeRequest, TodayStatus, ModifyFichajeRequest
)
from app.services.fichador import fichador
from app.services.storage import (
    get_schedules, get_schedule, save_schedule, delete_schedule,
    get_config, save_config, get_attendance as storage_get_attendance, save_attendance,
    get_calendar_events, save_calendar_event, delete_calendar_event
)
from app.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


async def _notify_telegram(action_name: str, result: dict):
    """Send Telegram screenshots after an action."""
    try:
        from app.services.telegram_bot import telegram_bot
        if telegram_bot.is_running:
            steps = fichador.get_debug_steps()
            logger.info(f"Telegram notify: {action_name}, {len(steps)} steps, bot running")
            await telegram_bot.send_screenshots_from_steps(
                steps, action_name,
                result.get("status", "error")
            )
            logger.info(f"Telegram notify sent: {action_name}")
        else:
            logger.info(f"Telegram bot not running, skip notify")
    except Exception as e:
        logger.error(f"Telegram notification failed: {e}", exc_info=True)


async def _notify_telegram_start(action_name: str):
    """Send instant 'action started' message before Playwright runs."""
    try:
        from app.services.telegram_bot import telegram_bot
        if telegram_bot.is_running:
            await telegram_bot.send_notification(f"⏳ *{action_name}...*")
    except Exception as e:
        logger.error(f"Telegram start notify failed: {e}")


# === 2FA Authentication ===
class LoginRequest(BaseModel):
    email: str
    password: str


class TwoFactorCodeRequest(BaseModel):
    code: str


@router.post("/auth/login")
async def start_login(request: LoginRequest, background_tasks: BackgroundTasks):
    """
    Start login process with 2FA support.
    Runs in background, poll /auth/status for progress.
    """
    # Start login in background
    background_tasks.add_task(
        fichador.login_with_2fa,
        email=request.email,
        password=request.password
    )
    
    return {
        "status": "started",
        "message": "Login iniciado. Consulta /auth/status para el progreso."
    }


@router.get("/auth/status")
async def get_auth_status():
    """Get current authentication status (poll this during login)."""
    return fichador.get_auth_status()


@router.post("/auth/2fa")
async def submit_2fa_code(request: TwoFactorCodeRequest):
    """Submit 2FA code during login process."""
    if fichador.auth_state.value != "waiting_2fa":
        return {
            "status": "error",
            "message": "No se está esperando un código 2FA"
        }
    
    fichador.set_2fa_code(request.code)
    return {
        "status": "success",
        "message": "Código enviado"
    }


@router.post("/auth/check-session")
async def check_session():
    """Check if current session is valid."""
    try:
        is_valid = fichador.is_session_valid()
        return {"valid": is_valid}
    except Exception as e:
        return {"valid": False, "error": str(e)}


@router.get("/auth/session-info")
async def get_session_info():
    """Get session details: user email, saved_at, time remaining."""
    from pathlib import Path
    import json
    from datetime import datetime

    session_file = Path("data/cookies/holded_session.json")
    if not session_file.exists():
        return {"active": False, "message": "No hay sesión guardada"}

    try:
        data = json.loads(session_file.read_text())
        saved_at_str = data.get("saved_at", "")
        saved_at = datetime.fromisoformat(saved_at_str)
        now = datetime.now()
        elapsed = (now - saved_at).total_seconds()
        ttl_seconds = max(0, 604800 - elapsed)
        days = int(ttl_seconds // 86400)
        hours = int((ttl_seconds % 86400) // 3600)
        minutes = int((ttl_seconds % 3600) // 60)

        user_email = data.get("user_email", "")
        if not user_email:
            # Fallback: try to find email from config
            try:
                config = get_config()
                user_email = config.get("holded_email", "")
            except:
                pass
        if not user_email:
            # Fallback: try to find email from .env settings
            user_email = settings.HOLDED_EMAIL or ""
        if not user_email:
            # Fallback: try to find email in cookies
            origins = data.get("origins", [])
            for o in origins:
                for cookie in o.get("cookies", []):
                    if "holded" in cookie.get("name", "").lower() and "email" in cookie.get("value", "").lower():
                        user_email = cookie.get("value", "")
                        break
        # If we found email via fallback, save it back to session file for next time
        if user_email and not data.get("user_email"):
            try:
                data["user_email"] = user_email
                session_file.write_text(json.dumps(data, indent=2))
            except:
                pass

        return {
            "active": ttl_seconds > 0,
            "user_email": user_email,
            "saved_at": saved_at.isoformat(),
            "ttl_days": days,
            "ttl_hours": hours,
            "ttl_minutes": minutes,
            "ttl_seconds": int(ttl_seconds),
        }
    except Exception as e:
        return {"active": False, "message": f"Error leyendo sesión: {str(e)}"}


@router.post("/auth/logout")
async def logout():
    """Clear saved session."""
    try:
        from pathlib import Path
        session_file = Path("data/cookies/holded_session.json")
        if session_file.exists():
            session_file.unlink()
        return {"status": "success", "message": "Sesión eliminada"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/config/headless")
async def get_headless_mode():
    """Get current headless mode setting."""
    from app.services.fichador import fichador
    return {"headless": fichador.headless}


@router.post("/config/headless")
async def set_headless_mode(request: dict):
    """Set headless mode (False = visible browser for debugging)."""
    from app.services.fichador import fichador
    from app.services.storage import get_config, save_config
    import os
    import subprocess

    headless = request.get("headless", True)
    fichador.headless = bool(headless)

    # Persist to config.json
    config = get_config()
    config["headless"] = fichador.headless
    save_config(config)

    if fichador.headless:
        return {"headless": True, "message": "Modo oculto (producción)"}
    else:
        # Check if DISPLAY is set
        has_display = bool(os.environ.get("DISPLAY"))
        if not has_display:
            # Try to start Xvfb automatically
            try:
                subprocess.Popen(
                    ['Xvfb', ':99', '-screen', '0', '1920x1080x24'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                await asyncio.sleep(1)
                os.environ['DISPLAY'] = ':99'
                has_display = True
                logger.info("Auto-started Xvfb on :99")
            except Exception as e:
                logger.error(f"Failed to auto-start Xvfb: {e}")

        if has_display:
            return {"headless": False, "message": "Modo visible activado - se abrirá el navegador", "display": os.environ.get("DISPLAY")}
        else:
            return {"headless": False, "message": "No se pudo iniciar Xvfb. Se usará modo oculto automáticamente.", "warning": True}


# === User Config Endpoints ===
@router.get("/config")
async def get_user_config():
    config = get_config()
    if not config:
        return {"holded_email": "", "timezone": "Europe/Madrid"}
    return config


@router.post("/config")
async def create_config(config: UserConfigCreate):
    data = config.model_dump()
    save_config(data)
    return data


@router.put("/config")
async def update_config(config: UserConfigUpdate):
    existing = get_config()
    if not existing:
        raise HTTPException(status_code=404, detail="No configuration found")
    
    update_data = config.model_dump(exclude_unset=True)
    existing.update(update_data)
    save_config(existing)
    return existing


# === Work Schedule Endpoints ===
@router.get("/schedules")
async def get_all_schedules():
    schedules = get_schedules()
    return schedules


@router.post("/schedules")
async def create_schedule(schedule: WorkScheduleCreate):
    data = schedule.model_dump()
    
    # Convert work_days list to work_days format for storage
    work_days = []
    for day_num in data.get("work_days", []):
        work_days.append({"day_of_week": day_num, "is_workday": True})
    data["work_days"] = work_days
    
    # If using simple mode, create a single work block
    if data.get("entry_time") and data.get("exit_time"):
        data["work_blocks"] = [
            {"entry": data["entry_time"], "exit": data["exit_time"]}
        ]
    
    result = save_schedule(data)
    
    # Reload scheduler
    from app.services.scheduler import scheduler
    if scheduler.is_running:
        scheduler._load_all_schedules()
    
    return result


@router.get("/schedules/{schedule_id}")
async def get_single_schedule(schedule_id: str):
    schedule = get_schedule(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule


@router.put("/schedules/{schedule_id}")
async def update_schedule(schedule_id: str, schedule: WorkScheduleUpdate):
    existing = get_schedule(schedule_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Schedule not found")
    
    update_data = schedule.model_dump(exclude_unset=True)
    
    # Convert work_days list to work_days format for storage
    if "work_days" in update_data:
        work_days = []
        for day_num in update_data["work_days"]:
            work_days.append({"day_of_week": day_num, "is_workday": True})
        update_data["work_days"] = work_days
    
    # If using simple mode, create a single work block
    if update_data.get("entry_time") and update_data.get("exit_time"):
        update_data["work_blocks"] = [
            {"entry": update_data["entry_time"], "exit": update_data["exit_time"]}
        ]
    
    existing.update(update_data)
    existing["updated_at"] = datetime.now().isoformat()
    result = save_schedule(existing)
    return result


@router.delete("/schedules/{schedule_id}")
async def delete_single_schedule(schedule_id: str):
    schedule = get_schedule(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    
    delete_schedule(schedule_id)
    
    # Reload scheduler
    from app.services.scheduler import scheduler
    if scheduler.is_running:
        scheduler._load_all_schedules()
    
    return MessageResponse(message="Schedule deleted")


@router.post("/schedules/reload")
async def reload_schedules():
    """Reload all schedules in the scheduler."""
    from app.services.scheduler import scheduler
    if scheduler.is_running:
        # Clear all jobs first
        for job in scheduler.scheduler.get_jobs():
            scheduler.scheduler.remove_job(job.id)
        # Reload
        scheduler._load_all_schedules()
        return MessageResponse(message="Schedules reloaded")
    return MessageResponse(message="Scheduler not running")


# === Calendar Event Endpoints ===
@router.get("/calendar")
async def get_calendar_events(
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None)
):
    events = get_calendar_events(year, month)
    return events


@router.post("/calendar")
async def create_calendar_event(event: CalendarEventCreate):
    data = event.model_dump()
    result = save_calendar_event(data)
    return result


@router.delete("/calendar/{event_id}")
async def delete_calendar_event(event_id: str):
    delete_calendar_event(event_id)
    return MessageResponse(message="Event deleted")


@router.get("/calendar/today")
async def check_today():
    return {"date": date.today().isoformat(), "is_workday": True}


# === Attendance Endpoints ===
@router.get("/attendance")
async def get_attendance(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None)
):
    logs = storage_get_attendance(
        start_date=start_date.isoformat() if start_date else None,
        end_date=end_date.isoformat() if end_date else None
    )
    return logs


@router.delete("/attendance/{record_id}")
async def delete_attendance_record(record_id: str):
    from app.services.storage import delete_attendance as storage_delete_attendance
    storage_delete_attendance(record_id)
    return {"status": "success", "message": "Registro eliminado"}


@router.get("/attendance/today")
async def get_today_status():
    from app.services.storage import get_schedules, get_attendance as storage_get_attendance
    from datetime import date as date_cls
    today = date_cls.today().isoformat()
    today_logs = storage_get_attendance(start_date=today, end_date=today)
    
    has_entry = False
    has_exit = False
    current_status = "not_started"
    entry_time = None
    exit_time = None
    total_hours = 0.0
    pause_minutes = 0

    if today_logs:
        log = today_logs[-1]
        entry_time = log.get("entry_time")
        exit_time = log.get("exit_time")
        pause_minutes = log.get("pause_minutes", 0)
        total_hours = log.get("total_hours", 0)
        current_status = log.get("status", "not_started")

        if entry_time:
            has_entry = True
        if exit_time:
            has_exit = True

    return TodayStatus(
        is_workday=True,
        has_entry=has_entry,
        has_exit=has_exit,
        current_status=current_status,
        entry_time=entry_time,
        exit_time=exit_time,
        pause_minutes=pause_minutes,
        total_hours=total_hours
    )


@router.post("/attendance/manual")
async def create_manual_attendance(attendance: AttendanceLogCreate):
    data = attendance.model_dump()
    result = save_attendance(data)
    return result


@router.get("/attendance/stats")
async def get_attendance_stats(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None)
):
    logs = storage_get_attendance(
        start_date=start_date.isoformat() if start_date else None,
        end_date=end_date.isoformat() if end_date else None
    )
    
    # Calculate stats
    total_hours = sum(l.get("total_hours", 0) for l in logs)
    total_days = len(logs)
    avg_hours = total_hours / total_days if total_days > 0 else 0
    
    return {
        "total_hours": total_hours,
        "total_days": total_days,
        "average_hours_per_day": avg_hours,
        "overtime_hours": 0
    }


# === Scheduler Endpoints ===
@router.get("/scheduler/status")
async def get_scheduler_status():
    from app.services.scheduler import scheduler
    return SchedulerStatus(**scheduler.get_status())


@router.post("/scheduler/start")
async def start_scheduler():
    from app.services.scheduler import scheduler
    await scheduler.start()
    return MessageResponse(message="Scheduler started")


@router.post("/scheduler/stop")
async def stop_scheduler():
    from app.services.scheduler import scheduler
    await scheduler.stop()
    return MessageResponse(message="Scheduler stopped")


@router.post("/scheduler/force")
async def force_fichaje(request: ForceFichajeRequest):
    """Execute a forced fichaje action."""
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Force fichaje request: fichaje_type={request.fichaje_type}, schedule_id={request.schedule_id}")

    from app.services.fichador import fichador
    from app.services.storage import get_schedules

    # Get the active schedule
    schedules = get_schedules()
    active_schedule = None
    for s in schedules:
        if s.get("is_active", True):
            active_schedule = s
            break

    if not active_schedule:
        logger.warning("No active schedule found")
        return MessageResponse(message="No hay horario activo", success=False)

    work_blocks = active_schedule.get("work_blocks", [])
    if not work_blocks:
        logger.warning("Active schedule has no work blocks")
        return MessageResponse(message="El horario activo no tiene bloques de trabajo", success=False)

    fichaje_type = request.fichaje_type
    now = datetime.now()
    today_str = date.today().isoformat()
    action_names = {
        "entry": "Fichaje iniciado",
        "pause_start": "Fichaje pausado",
        "pause_end": "Fichaje reanudado",
        "exit": "Fichaje finalizado",
        "manual": "Fichaje manual"
    }

    if fichaje_type == "entry":
        await _notify_telegram_start("▶️ Iniciando fichaje")
        result = await fichador.start_live_tracking()
        if result.get("status") == "success":
            save_attendance({
                "date": today_str,
                "entry_time": now.isoformat(),
                "status": "in_progress",
                "source": "manual"
            })
        await _notify_telegram(action_names.get(fichaje_type, fichaje_type), result)
        return result
    elif fichaje_type == "pause_start":
        await _notify_telegram_start("⏸ Pausando fichaje")
        result = await fichador.pause_live_tracking()
        if result.get("status") == "success":
            save_attendance({
                "date": today_str,
                "status": "paused",
                "source": "manual"
            })
        await _notify_telegram(action_names.get(fichaje_type, fichaje_type), result)
        return result
    elif fichaje_type == "pause_end":
        await _notify_telegram_start("▶️ Reanudando fichaje")
        result = await fichador.start_live_tracking()
        if result.get("status") == "success":
            save_attendance({
                "date": today_str,
                "status": "in_progress",
                "source": "manual"
            })
        await _notify_telegram(action_names.get(fichaje_type, fichaje_type), result)
        return result
    elif fichaje_type == "exit":
        await _notify_telegram_start("⏹ Finalizando fichaje")
        result = await fichador.stop_live_tracking()
        if result.get("status") == "success":
            save_attendance({
                "date": today_str,
                "exit_time": now.isoformat(),
                "status": "completed",
                "source": "manual"
            })
        await _notify_telegram(action_names.get(fichaje_type, fichaje_type), result)
        return result
    elif fichaje_type == "manual":
        await _notify_telegram_start("📅 Fichaje manual")
        location = active_schedule.get("location") or "ARCO C.B."
        result = await fichador.fichar_manual(work_blocks=work_blocks, location=location)
        await _notify_telegram(action_names.get(fichaje_type, fichaje_type), result)
        return result
    else:
        logger.error(f"Unknown fichaje_type: {fichaje_type}")
        return MessageResponse(message=f"Tipo de fichaje no válido: {fichaje_type}", success=False)


class ManualFichajeRequest(BaseModel):
    schedule_id: Optional[str] = None
    location: Optional[str] = None
    target_date: Optional[str] = None


@router.post("/attendance/manual-fichaje")
async def manual_fichaje(request: ManualFichajeRequest):
    """Execute a manual fichaje using the Holded 'Añadir fichaje' form."""
    from app.services.fichador import fichador
    from app.services.storage import get_schedules, get_schedule

    if request.schedule_id:
        schedule = get_schedule(request.schedule_id)
    else:
        schedules = get_schedules()
        schedule = None
        for s in schedules:
            if s.get("is_active", True):
                schedule = s
                break

    if not schedule:
        raise HTTPException(status_code=404, detail="No hay horario activo")

    work_blocks = schedule.get("work_blocks", [])
    if not work_blocks:
        raise HTTPException(status_code=400, detail="El horario no tiene bloques de trabajo")

    target = date.fromisoformat(request.target_date) if request.target_date else date.today()

    # Use location from request, or from schedule, or default
    fichaje_location = request.location or schedule.get("location") or "ARCO C.B."

    await _notify_telegram_start(f"📅 Fichaje manual {target.isoformat()}")
    result = await fichador.fichar_manual(
        work_blocks=work_blocks,
        target_date=target,
        location=fichaje_location
    )

    if result.get("status") == "success":
        # Calculate hours from work blocks
        total_minutes = 0
        pause_minutes = 0
        first_entry = None
        last_exit = None

        for block in work_blocks:
            try:
                entry_parts = block.get("entry", "0:0").split(":")
                exit_parts = block.get("exit", "0:0").split(":")
                entry_mins = int(entry_parts[0]) * 60 + int(entry_parts[1])
                exit_mins = int(exit_parts[0]) * 60 + int(exit_parts[1])
                block_minutes = exit_mins - entry_mins
                block_type = block.get("type", "Trabajado")

                if block_type == "Pausa":
                    pause_minutes += block_minutes
                else:
                    total_minutes += block_minutes

                if first_entry is None or block.get("entry", "") < first_entry:
                    first_entry = block.get("entry", "")
                if last_exit is None or block.get("exit", "") > last_exit:
                    last_exit = block.get("exit", "")
            except:
                pass

        save_attendance({
            "date": target.isoformat(),
            "location": fichaje_location,
            "entry_time": f"{target.isoformat()}T{first_entry}:00" if first_entry else None,
            "exit_time": f"{target.isoformat()}T{last_exit}:00" if last_exit else None,
            "pause_minutes": pause_minutes,
            "total_hours": round(total_minutes / 60, 2),
            "work_blocks": work_blocks,
            "status": "completed",
            "source": "manual"
        })

    await _notify_telegram(f"Fichaje manual {target.isoformat()}", result)
    return result


@router.post("/attendance/modify-fichaje")
async def modify_fichaje(request: ModifyFichajeRequest):
    """Modify an existing fichaje in Holded."""
    from app.services.fichador import fichador

    work_blocks = [
        {"entry": b.entry, "exit": b.exit, "type": b.type}
        for b in request.work_blocks
    ]

    result = await fichador.modificar_fichaje(
        target_date=request.target_date,
        work_blocks=work_blocks,
        location=request.location
    )
    return result


@router.post("/attendance/corregir-fichaje")
async def corregir_fichaje():
    """Correct today's fichaje by editing it with the active schedule's work blocks."""
    from app.services.fichador import fichador
    from app.services.storage import get_schedules

    schedules = get_schedules()
    schedule = None
    for s in schedules:
        if s.get("is_active", True):
            schedule = s
            break

    if not schedule:
        raise HTTPException(status_code=404, detail="No hay horario activo")

    work_blocks = schedule.get("work_blocks", [])
    if not work_blocks:
        raise HTTPException(status_code=400, detail="El horario no tiene bloques de trabajo")

    location = schedule.get("location") or "ARCO C.B."
    target = date.today()

    await _notify_telegram_start(f"🔧 Corrigiendo fichaje {target.isoformat()}")
    result = await fichador.modificar_fichaje(
        target_date=target,
        work_blocks=work_blocks,
        location=location
    )
    await _notify_telegram(f"Corregir fichaje {target.isoformat()}", result)
    return result


# === Logs Endpoints ===
@router.get("/logs")
async def get_logs(
    level: Optional[str] = Query(None),
    module: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000)
):
    """Read actual log entries from the application log file."""
    from pathlib import Path
    import re

    log_dir = Path("logs")
    log_entries = []

    if not log_dir.exists():
        return []

    log_files = sorted(log_dir.glob("*.log"), reverse=True)
    for log_file in log_files[:3]:
        try:
            content = log_file.read_text(errors="ignore")
            for line in content.strip().split("\n"):
                if not line.strip():
                    continue
                match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+).*?\[(\w+)\].*?app\.(\w+):?\s*(.*)', line)
                if match:
                    ts, lvl, mod, msg = match.groups()
                    if level and lvl.lower() != level.lower():
                        continue
                    if module and mod.lower() != module.lower():
                        continue
                    log_entries.append({
                        "timestamp": ts,
                        "level": lvl.lower(),
                        "module": mod,
                        "message": msg.strip()
                    })
        except Exception:
            continue

    log_entries.sort(key=lambda x: x["timestamp"], reverse=True)
    return log_entries[:limit]


@router.delete("/logs/clean")
async def clean_logs(days_to_keep: int = Query(30, ge=1)):
    from pathlib import Path
    import time
    log_dir = Path("logs")
    if not log_dir.exists():
        return MessageResponse(message="No hay logs que limpiar")
    cutoff = time.time() - (days_to_keep * 86400)
    cleaned = 0
    for f in log_dir.glob("*.log"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            cleaned += 1
    return MessageResponse(message=f"Eliminados {cleaned} archivos de log")


@router.get("/logs/stream")
async def stream_logs():
    """SSE endpoint for live log streaming."""
    from fastapi.responses import StreamingResponse
    from pathlib import Path
    import re
    import asyncio

    async def generate():
        log_dir = Path("logs")
        last_pos = 0

        while True:
            if not log_dir.exists():
                await asyncio.sleep(2)
                continue

            log_files = sorted(log_dir.glob("*.log"), reverse=True)
            if log_files:
                log_file = log_files[0]
                try:
                    content = log_file.read_text(errors="ignore")
                    lines = content.strip().split("\n")
                    new_lines = lines[last_pos:]
                    last_pos = len(lines)

                    for line in new_lines:
                        if not line.strip():
                            continue
                        match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+).*?\[(\w+)\].*?app\.(\w+):?\s*(.*)', line)
                        if match:
                            ts, lvl, mod, msg = match.groups()
                            import json
                            entry = json.dumps({
                                "timestamp": ts, "level": lvl.lower(),
                                "module": mod, "message": msg.strip()
                            })
                            yield f"data: {entry}\n\n"
                except Exception:
                    pass

            await asyncio.sleep(3)

    return StreamingResponse(generate(), media_type="text/event-stream")


# === Debug Endpoints ===
@router.get("/debug/steps")
async def get_debug_steps():
    """Get debug steps from last operation."""
    from app.services.fichador import fichador
    return {"steps": fichador.get_debug_steps()}


@router.get("/debug/screenshot/{filename}")
async def get_debug_screenshot(filename: str):
    """Serve a debug screenshot file."""
    from fastapi.responses import FileResponse
    from pathlib import Path
    filepath = Path("data/debug") / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Screenshot not found")
    return FileResponse(str(filepath), media_type="image/png")


# === Telegram Bot Endpoints ===
class TelegramConfigUpdate(BaseModel):
    token: Optional[str] = None
    chat_id: Optional[str] = None
    enabled: Optional[bool] = None
    screenshot_mode: Optional[str] = None


@router.get("/telegram/config")
async def get_telegram_config():
    """Get Telegram bot configuration (token is masked)."""
    config = get_config()
    token = config.get("telegram_token", "")
    masked = ""
    if token and len(token) > 10:
        masked = token[:6] + "..." + token[-4:]

    return {
        "token_masked": masked,
        "chat_id": config.get("telegram_chat_id", ""),
        "enabled": config.get("telegram_enabled", False),
        "screenshot_mode": config.get("telegram_screenshot_mode", "last")
    }


@router.put("/telegram/config")
async def update_telegram_config(body: TelegramConfigUpdate):
    """Update Telegram bot configuration and restart bot if needed."""
    from app.services.telegram_bot import telegram_bot

    config = get_config()

    if body.token is not None:
        config["telegram_token"] = body.token
    if body.chat_id is not None:
        config["telegram_chat_id"] = body.chat_id
    if body.enabled is not None:
        config["telegram_enabled"] = body.enabled
    if body.screenshot_mode is not None:
        config["telegram_screenshot_mode"] = body.screenshot_mode

    save_config(config)

    # Restart bot with new config
    if telegram_bot.is_running:
        await telegram_bot.stop()

    tg_token = config.get("telegram_token", "")
    tg_chat_id = config.get("telegram_chat_id", "")
    tg_enabled = config.get("telegram_enabled", False)
    tg_mode = config.get("telegram_screenshot_mode", "last")

    if tg_enabled and tg_token and tg_chat_id:
        telegram_bot.configure(tg_token, tg_chat_id, tg_mode)
        await telegram_bot.start()
        return {"status": "success", "message": "Bot de Telegram configurado e iniciado"}
    else:
        return {"status": "success", "message": "Configuración guardada (bot desactivado)"}


@router.post("/telegram/test")
async def test_telegram_connection():
    """Send a test message to the configured Telegram chat."""
    from app.services.telegram_bot import telegram_bot

    if not telegram_bot.is_running:
        return {"status": "error", "message": "El bot de Telegram no está activo"}

    try:
        await telegram_bot.send_notification("🧪 *Mensaje de prueba*\n\nEl bot de Telegram funciona correctamente.")
        return {"status": "success", "message": "Mensaje de prueba enviado"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/telegram/status")
async def get_telegram_status():
    """Get Telegram bot runtime status."""
    from app.services.telegram_bot import telegram_bot
    return telegram_bot.get_status()
