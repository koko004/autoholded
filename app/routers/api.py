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


@router.get("/attendance/today")
async def get_today_status():
    return TodayStatus(
        is_workday=True, has_entry=False, has_exit=False,
        current_status="not_started", entry_time=None, exit_time=None,
        pause_minutes=0, total_hours=0.0
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

    if fichaje_type == "entry":
        result = await fichador.start_live_tracking()
        return result
    elif fichaje_type == "pause_start":
        result = await fichador.pause_live_tracking()
        return result
    elif fichaje_type == "pause_end":
        result = await fichador.start_live_tracking()
        return result
    elif fichaje_type == "exit":
        result = await fichador.stop_live_tracking()
        return result
    elif fichaje_type == "manual":
        location = active_schedule.get("location") or "ARCO C.B."
        result = await fichador.fichar_manual(work_blocks=work_blocks, location=location)
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

    result = await fichador.fichar_manual(
        work_blocks=work_blocks,
        target_date=target,
        location=fichaje_location
    )
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


# === Logs Endpoints ===
@router.get("/logs")
async def get_logs(
    level: Optional[str] = Query(None),
    module: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000)
):
    return []


@router.delete("/logs/clean")
async def clean_logs(days_to_keep: int = Query(30, ge=1)):
    return MessageResponse(message=f"Cleaned logs older than {days_to_keep} days")


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
