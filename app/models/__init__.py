"""SQLAlchemy models for the application."""
from datetime import datetime, date, time
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Date, Time,
    ForeignKey, Text, JSON
)
from sqlalchemy.orm import relationship
from app.database import Base


class UserConfig(Base):
    """User configuration for Holded credentials."""
    __tablename__ = "user_config"
    
    id = Column(Integer, primary_key=True, index=True)
    holded_email = Column(String(255), nullable=False)
    holded_password_encrypted = Column(Text, nullable=False)
    timezone = Column(String(50), default="Europe/Madrid")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WorkSchedule(Base):
    """Work schedule configuration."""
    __tablename__ = "work_schedule"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    entry_time = Column(Time, nullable=False)
    exit_time = Column(Time, nullable=False)
    pause_start = Column(Time, nullable=True)
    pause_end = Column(Time, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    work_days = relationship("WorkDay", back_populates="schedule", cascade="all, delete-orphan")


class WorkDay(Base):
    """Days of the week for a schedule."""
    __tablename__ = "work_days"
    
    id = Column(Integer, primary_key=True, index=True)
    schedule_id = Column(Integer, ForeignKey("work_schedule.id"), nullable=False)
    day_of_week = Column(Integer, nullable=False)  # 0=Monday, 6=Sunday
    is_workday = Column(Boolean, default=True)
    
    schedule = relationship("WorkSchedule", back_populates="work_days")


class CalendarEvent(Base):
    """Calendar events (holidays, vacations, special schedules)."""
    __tablename__ = "calendar_events"
    
    id = Column(Integer, primary_key=True, index=True)
    event_date = Column(Date, nullable=False)
    event_type = Column(String(50), nullable=False)  # holiday, vacation, special_schedule
    schedule_id = Column(Integer, ForeignKey("work_schedule.id"), nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AttendanceLog(Base):
    """Attendance/clock-in records."""
    __tablename__ = "attendance_log"
    
    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False)
    entry_time = Column(DateTime, nullable=True)
    exit_time = Column(DateTime, nullable=True)
    pause_minutes = Column(Integer, default=0)
    status = Column(String(20), default="pending")  # pending, completed, error
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class NotificationConfig(Base):
    """Notification settings."""
    __tablename__ = "notification_config"
    
    id = Column(Integer, primary_key=True, index=True)
    email_enabled = Column(Boolean, default=True)
    email_recipients = Column(Text, nullable=True)  # JSON array
    webhook_enabled = Column(Boolean, default=False)
    webhook_url = Column(String(500), nullable=True)
    notify_on_success = Column(Boolean, default=True)
    notify_on_error = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SystemLog(Base):
    """System logs for monitoring."""
    __tablename__ = "system_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    level = Column(String(20), nullable=False)  # info, warning, error
    module = Column(String(50), nullable=False)  # scheduler, fichador, api
    message = Column(Text, nullable=False)
    details = Column(JSON, nullable=True)
