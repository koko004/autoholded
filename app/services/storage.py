"""Simple JSON file-based storage for schedules and config."""
import json
import logging
from datetime import datetime, date, time
from pathlib import Path
from typing import Optional, List, Dict, Any
from uuid import uuid4

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
SCHEDULES_FILE = DATA_DIR / "schedules.json"
CONFIG_FILE = DATA_DIR / "config.json"
ATTENDANCE_FILE = DATA_DIR / "attendance.json"
CALENDAR_FILE = DATA_DIR / "calendar.json"


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(file_path: Path) -> Dict[str, Any]:
    """Load data from JSON file."""
    _ensure_data_dir()
    if file_path.exists():
        try:
            return json.loads(file_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading {file_path}: {e}")
            return {}
    return {}


def _save_json(file_path: Path, data: Dict[str, Any]):
    """Save data to JSON file."""
    _ensure_data_dir()
    try:
        file_path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    except IOError as e:
        logger.error(f"Error saving {file_path}: {e}")


# === Schedules ===
def get_schedules() -> List[Dict[str, Any]]:
    """Get all schedules."""
    data = _load_json(SCHEDULES_FILE)
    return data.get("schedules", [])


def get_schedule(schedule_id: str) -> Optional[Dict[str, Any]]:
    """Get a schedule by ID."""
    schedules = get_schedules()
    for s in schedules:
        if s.get("id") == schedule_id:
            return s
    return None


def save_schedule(schedule: Dict[str, Any]) -> Dict[str, Any]:
    """Create or update a schedule."""
    data = _load_json(SCHEDULES_FILE)
    schedules = data.get("schedules", [])
    
    if schedule.get("id"):
        # Update existing
        for i, s in enumerate(schedules):
            if s.get("id") == schedule["id"]:
                schedule["updated_at"] = datetime.now().isoformat()
                schedules[i] = schedule
                break
    else:
        # Create new
        schedule["id"] = str(uuid4())
        schedule["created_at"] = datetime.now().isoformat()
        schedule["updated_at"] = datetime.now().isoformat()
        schedules.append(schedule)
    
    data["schedules"] = schedules
    _save_json(SCHEDULES_FILE, data)
    return schedule


def delete_schedule(schedule_id: str) -> bool:
    """Delete a schedule."""
    data = _load_json(SCHEDULES_FILE)
    schedules = data.get("schedules", [])
    data["schedules"] = [s for s in schedules if s.get("id") != schedule_id]
    _save_json(SCHEDULES_FILE, data)
    return True


# === Config ===
def get_config() -> Dict[str, Any]:
    """Get config."""
    return _load_json(CONFIG_FILE)


def save_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Save config."""
    config["updated_at"] = datetime.now().isoformat()
    _save_json(CONFIG_FILE, config)
    return config


# === Attendance ===
def get_attendance(start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get attendance logs, optionally filtered by date range."""
    data = _load_json(ATTENDANCE_FILE)
    logs = data.get("logs", [])
    
    if start_date:
        logs = [l for l in logs if l.get("date", "") >= start_date]
    if end_date:
        logs = [l for l in logs if l.get("date", "") <= end_date]
    
    return logs


def save_attendance(log: Dict[str, Any]) -> Dict[str, Any]:
    """Save an attendance log. Upserts by date (one record per day).
    
    When saving a live tracking action (entry/pause/stop), only updates
    relevant fields so old stale data doesn't persist.
    """
    data = _load_json(ATTENDANCE_FILE)
    logs = data.get("logs", [])

    target_date = str(log.get("date", ""))

    # Find existing record for this date
    existing_idx = None
    for i, l in enumerate(logs):
        if str(l.get("date", "")) == target_date:
            existing_idx = i
            break

    if existing_idx is not None:
        existing = logs[existing_idx]
        source = log.get("source", "")

        if source in ("scheduler", "manual") and log.get("status"):
            action_status = log.get("status")

            if action_status == "in_progress" and log.get("entry_time"):
                existing["entry_time"] = log["entry_time"]
                existing["status"] = "in_progress"
                existing["source"] = source
            elif action_status == "paused":
                existing["status"] = "paused"
                existing["source"] = source
                if log.get("pause_minutes"):
                    existing["pause_minutes"] = log["pause_minutes"]
            elif action_status == "completed":
                if log.get("exit_time"):
                    existing["exit_time"] = log["exit_time"]
                existing["status"] = "completed"
                existing["source"] = source
                if log.get("pause_minutes"):
                    existing["pause_minutes"] = log["pause_minutes"]
        else:
            for key, value in log.items():
                if value is not None and key != "id":
                    existing[key] = value

        existing["updated_at"] = datetime.now().isoformat()
        logs[existing_idx] = existing
        result = existing
    else:
        log["id"] = str(uuid4())
        log["created_at"] = datetime.now().isoformat()
        if "pause_minutes" not in log:
            log["pause_minutes"] = 0
        if "total_hours" not in log:
            log["total_hours"] = 0.0
        logs.append(log)
        result = log

    data["logs"] = logs
    _save_json(ATTENDANCE_FILE, data)
    return result


def delete_attendance(record_id: str) -> bool:
    """Delete an attendance record by ID."""
    data = _load_json(ATTENDANCE_FILE)
    logs = data.get("logs", [])
    data["logs"] = [l for l in logs if l.get("id") != record_id]
    _save_json(ATTENDANCE_FILE, data)
    return True


# === Calendar ===
def get_calendar_events(year: Optional[int] = None, month: Optional[int] = None) -> List[Dict[str, Any]]:
    """Get calendar events, optionally filtered."""
    data = _load_json(CALENDAR_FILE)
    events = data.get("events", [])
    
    if year and month:
        prefix = f"{year}-{month:02d}"
        events = [e for e in events if str(e.get("event_date", "")).startswith(prefix)]
    
    return events


def save_calendar_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Save a calendar event."""
    data = _load_json(CALENDAR_FILE)
    events = data.get("events", [])
    
    event["id"] = str(uuid4())
    event["created_at"] = datetime.now().isoformat()
    events.append(event)
    
    data["events"] = events
    _save_json(CALENDAR_FILE, data)
    return event


def delete_calendar_event(event_id: str) -> bool:
    """Delete a calendar event."""
    data = _load_json(CALENDAR_FILE)
    events = data.get("events", [])
    data["events"] = [e for e in events if e.get("id") != event_id]
    _save_json(CALENDAR_FILE, data)
    return True
