"""Pydantic schemas for API request/response models."""
from datetime import datetime, date, time
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, EmailStr, Field


# === User Config Schemas ===
class UserConfigBase(BaseModel):
    holded_email: EmailStr
    timezone: str = "Europe/Madrid"


class UserConfigCreate(UserConfigBase):
    holded_password: str


class UserConfigResponse(UserConfigBase):
    id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class UserConfigUpdate(BaseModel):
    holded_email: Optional[EmailStr] = None
    holded_password: Optional[str] = None
    timezone: Optional[str] = None
    notifications: Optional[Dict[str, Any]] = None


# === Work Schedule Schemas ===
class WorkBlock(BaseModel):
    """A single work block (entry to exit)."""
    entry: time
    exit: time
    type: Optional[str] = "Trabajado"  # "Trabajado" or "Pausa"


class WorkScheduleBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    # Simple mode (single block)
    entry_time: Optional[time] = None
    exit_time: Optional[time] = None
    pause_start: Optional[time] = None
    pause_end: Optional[time] = None
    # Split shift mode (multiple blocks)
    work_blocks: List[WorkBlock] = []
    is_active: bool = True


class WorkScheduleCreate(BaseModel):
    name: str = Field(..., min_length=1)
    entry_time: Optional[str] = None
    exit_time: Optional[str] = None
    pause_start: Optional[str] = None
    pause_end: Optional[str] = None
    work_blocks: Optional[List[WorkBlock]] = None
    location: Optional[str] = None
    is_active: bool = True


class WorkScheduleResponse(BaseModel):
    id: str
    name: str
    entry_time: Optional[time] = None
    exit_time: Optional[time] = None
    pause_start: Optional[time] = None
    pause_end: Optional[time] = None
    work_blocks: List[WorkBlock] = []
    location: Optional[str] = None
    is_active: bool = True
    work_days: List[Dict[str, Any]] = []
    created_at: str
    updated_at: str
    
    class Config:
        from_attributes = True


class WorkScheduleUpdate(BaseModel):
    name: Optional[str] = None
    entry_time: Optional[str] = None
    exit_time: Optional[str] = None
    pause_start: Optional[str] = None
    pause_end: Optional[str] = None
    work_blocks: Optional[List[WorkBlock]] = None
    location: Optional[str] = None
    is_active: Optional[bool] = None
    work_days: Optional[List[int]] = None


class WorkDayBase(BaseModel):
    day_of_week: int = Field(..., ge=0, le=6)
    is_workday: bool = True


class WorkDayCreate(WorkDayBase):
    pass


class WorkDayResponse(WorkDayBase):
    id: int
    schedule_id: int
    
    class Config:
        from_attributes = True


# === Calendar Event Schemas ===
class CalendarEventBase(BaseModel):
    event_date: date
    event_type: str = Field(..., pattern="^(holiday|vacation|special_schedule)$")
    schedule_id: Optional[int] = None
    description: Optional[str] = None


class CalendarEventCreate(CalendarEventBase):
    pass


class CalendarEventResponse(CalendarEventBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


# === Attendance Log Schemas ===
class AttendanceLogBase(BaseModel):
    date: date
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    pause_minutes: int = 0
    total_hours: float = 0.0
    status: Optional[str] = None
    source: Optional[str] = None
    location: Optional[str] = None
    work_blocks: Optional[List[Dict[str, Any]]] = None
    notes: Optional[str] = None


class AttendanceLogCreate(AttendanceLogBase):
    pass


class AttendanceLogResponse(AttendanceLogBase):
    id: int
    status: str
    created_at: datetime
    
    class Config:
        from_attributes = True


# === Notification Config Schemas ===
class NotificationConfigBase(BaseModel):
    email_enabled: bool = True
    email_recipients: Optional[List[str]] = None
    webhook_enabled: bool = False
    webhook_url: Optional[str] = None
    notify_on_success: bool = True
    notify_on_error: bool = True


class NotificationConfigCreate(NotificationConfigBase):
    pass


class NotificationConfigResponse(NotificationConfigBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


# === System Log Schemas ===
class SystemLogResponse(BaseModel):
    id: int
    timestamp: datetime
    level: str
    module: str
    message: str
    details: Optional[dict] = None
    
    class Config:
        from_attributes = True


# === Common Schemas ===
class MessageResponse(BaseModel):
    message: str
    success: bool = True


class ErrorResponse(BaseModel):
    detail: str
    success: bool = False


class SchedulerStatus(BaseModel):
    is_running: bool
    next_fichaje: Optional[datetime] = None
    last_fichaje: Optional[datetime] = None
    active_jobs: List[str] = []


class ForceFichajeRequest(BaseModel):
    fichaje_type: str = Field(..., pattern="^(entry|exit|pause_start|pause_end|manual)$")
    schedule_id: Optional[str] = None


class EditWorkBlock(BaseModel):
    entry: str = Field(..., pattern="^\\d{2}:\\d{2}$")
    exit: str = Field(..., pattern="^\\d{2}:\\d{2}$")
    type: str = Field(default="Trabajado", pattern="^(Trabajado|Pausa)$")


class ModifyFichajeRequest(BaseModel):
    target_date: date
    work_blocks: List[EditWorkBlock]
    location: Optional[str] = None


class TodayStatus(BaseModel):
    is_workday: bool
    has_entry: bool
    has_exit: bool
    current_status: str  # not_started, working, paused, finished
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    pause_minutes: int = 0
    total_hours: float = 0.0
