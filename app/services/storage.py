"""JSON file-based storage with file locking for concurrency safety."""
import json
import logging
from datetime import datetime, date, time
from pathlib import Path
from typing import Optional, List, Dict, Any
from uuid import uuid4
from filelock import FileLock

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
LOCKS_DIR = DATA_DIR / ".locks"
SCHEDULES_FILE = DATA_DIR / "schedules.json"
CONFIG_FILE = DATA_DIR / "config.json"
ATTENDANCE_FILE = DATA_DIR / "attendance.json"
CALENDAR_FILE = DATA_DIR / "calendar.json"


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOCKS_DIR.mkdir(parents=True, exist_ok=True)


def _get_lock(file_path: Path) -> FileLock:
    """Get a file lock for the given file path."""
    lock_path = LOCKS_DIR / f"{file_path.name}.lock"
    return FileLock(str(lock_path))


def _read_json(file_path: Path) -> Dict[str, Any]:
    """Read JSON file WITHOUT acquiring a lock (caller must hold it)."""
    _ensure_data_dir()
    if file_path.exists():
        try:
            return json.loads(file_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading {file_path}: {e}")
            return {}
    return {}


def _write_json(file_path: Path, data: Dict[str, Any]):
    """Write JSON file WITHOUT acquiring a lock (caller must hold it)."""
    _ensure_data_dir()
    try:
        file_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8"
        )
    except IOError as e:
        logger.error(f"Error saving {file_path}: {e}")


def _load_json(file_path: Path) -> Dict[str, Any]:
    """Load data from JSON file with file locking."""
    lock = _get_lock(file_path)
    with lock:
        return _read_json(file_path)


def _save_json(file_path: Path, data: Dict[str, Any]):
    """Save data to JSON file with file locking."""
    lock = _get_lock(file_path)
    with lock:
        _write_json(file_path, data)


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


def get_default_schedule() -> Optional[Dict[str, Any]]:
    """Get the schedule marked as default."""
    schedules = get_schedules()
    for s in schedules:
        if s.get("is_default"):
            return s
    return None


def save_schedule(schedule: Dict[str, Any]) -> Dict[str, Any]:
    """Create or update a schedule."""
    lock = _get_lock(SCHEDULES_FILE)
    with lock:
        data = _read_json(SCHEDULES_FILE)
        schedules = data.get("schedules", [])

        # If this schedule is marked as default, clear default from others
        if schedule.get("is_default"):
            for s in schedules:
                if s.get("id") != schedule.get("id"):
                    s["is_default"] = False

        if schedule.get("id"):
            for i, s in enumerate(schedules):
                if s.get("id") == schedule["id"]:
                    schedule["updated_at"] = datetime.now().isoformat()
                    schedules[i] = schedule
                    break
        else:
            schedule["id"] = str(uuid4())
            schedule["created_at"] = datetime.now().isoformat()
            schedule["updated_at"] = datetime.now().isoformat()
            schedules.append(schedule)

        data["schedules"] = schedules
        _write_json(SCHEDULES_FILE, data)
        return schedule


def delete_schedule(schedule_id: str) -> bool:
    """Delete a schedule."""
    lock = _get_lock(SCHEDULES_FILE)
    with lock:
        data = _read_json(SCHEDULES_FILE)
        schedules = data.get("schedules", [])
        data["schedules"] = [s for s in schedules if s.get("id") != schedule_id]
        _write_json(SCHEDULES_FILE, data)
        return True


# === Config ===
def get_config() -> Dict[str, Any]:
    """Get config."""
    return _load_json(CONFIG_FILE)


def save_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Save config."""
    config["updated_at"] = datetime.now().isoformat()
    lock = _get_lock(CONFIG_FILE)
    with lock:
        _write_json(CONFIG_FILE, config)
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
    """Save an attendance log. Upserts by date (one record per day)."""
    lock = _get_lock(ATTENDANCE_FILE)
    with lock:
        data = _read_json(ATTENDANCE_FILE)
        logs = data.get("logs", [])

        target_date = str(log.get("date", ""))

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
        _write_json(ATTENDANCE_FILE, data)
        return result


def delete_attendance(record_id: str) -> bool:
    """Delete an attendance record by ID."""
    lock = _get_lock(ATTENDANCE_FILE)
    with lock:
        data = _read_json(ATTENDANCE_FILE)
        logs = data.get("logs", [])
        data["logs"] = [l for l in logs if l.get("id") != record_id]
        _write_json(ATTENDANCE_FILE, data)
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
    lock = _get_lock(CALENDAR_FILE)
    with lock:
        data = _read_json(CALENDAR_FILE)
        events = data.get("events", [])

        event["id"] = str(uuid4())
        event["created_at"] = datetime.now().isoformat()
        events.append(event)

        data["events"] = events
        _write_json(CALENDAR_FILE, data)
        return event


def delete_calendar_event(event_id: str) -> bool:
    """Delete a calendar event."""
    lock = _get_lock(CALENDAR_FILE)
    with lock:
        data = _read_json(CALENDAR_FILE)
        events = data.get("events", [])
        data["events"] = [e for e in events if e.get("id") != event_id]
        _write_json(CALENDAR_FILE, data)
        return True


def get_schedule_assignment(target_date: str) -> Optional[Dict[str, Any]]:
    """Get the schedule assignment for a specific date.
    
    Args:
        target_date: Date string in YYYY-MM-DD format
    
    Returns:
        The schedule assignment event if found, None otherwise.
    """
    events = get_calendar_events()
    for event in events:
        if (event.get("event_type") == "schedule_assignment" 
            and event.get("event_date") == target_date):
            return event
    return None


def save_schedule_assignment(target_date: str, schedule_id: str, schedule_name: str) -> Dict[str, Any]:
    """Save or update a schedule assignment for a specific date.
    
    If an assignment already exists for the date, it will be replaced.
    """
    lock = _get_lock(CALENDAR_FILE)
    with lock:
        data = _read_json(CALENDAR_FILE)
        events = data.get("events", [])
        
        # Remove existing assignment for this date
        events = [
            e for e in events 
            if not (e.get("event_type") == "schedule_assignment" 
                    and e.get("event_date") == target_date)
        ]
        
        # Add new assignment
        new_event = {
            "id": str(uuid4()),
            "event_date": target_date,
            "event_type": "schedule_assignment",
            "schedule_id": schedule_id,
            "description": schedule_name,
            "created_at": datetime.now().isoformat()
        }
        events.append(new_event)
        
        data["events"] = events
        _write_json(CALENDAR_FILE, data)
        return new_event


def delete_schedule_assignment(target_date: str) -> bool:
    """Delete schedule assignment for a specific date."""
    lock = _get_lock(CALENDAR_FILE)
    with lock:
        data = _read_json(CALENDAR_FILE)
        events = data.get("events", [])
        data["events"] = [
            e for e in events 
            if not (e.get("event_type") == "schedule_assignment" 
                    and e.get("event_date") == target_date)
        ]
        _write_json(CALENDAR_FILE, data)
        return True


def get_week_assignments(year: int, week_start: str) -> List[Dict[str, Any]]:
    """Get all schedule assignments for a week starting at week_start date.
    
    Args:
        year: The year
        week_start: The Monday date string (YYYY-MM-DD)
    """
    from datetime import timedelta
    events = get_calendar_events(year=year)
    week_dates = []
    start = date.fromisoformat(week_start)
    for i in range(7):
        d = start + timedelta(days=i)
        week_dates.append(d.isoformat())
    
    return [
        e for e in events
        if e.get("event_type") == "schedule_assignment"
        and e.get("event_date") in week_dates
    ]
