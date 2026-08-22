"""Tests for storage module."""
import json
import pytest
from pathlib import Path
from app.services.storage import (
    _load_json, _save_json, _ensure_data_dir,
    get_schedules, get_schedule, save_schedule, delete_schedule,
    get_config, save_config,
    get_attendance, save_attendance, delete_attendance,
    get_calendar_events, save_calendar_event, delete_calendar_event,
    DATA_DIR, SCHEDULES_FILE, CONFIG_FILE, ATTENDANCE_FILE, CALENDAR_FILE
)


@pytest.fixture(autouse=True)
def setup_test_data(tmp_path, monkeypatch):
    """Use a temporary directory for all test data."""
    monkeypatch.setattr("app.services.storage.DATA_DIR", tmp_path)
    monkeypatch.setattr("app.services.storage.SCHEDULES_FILE", tmp_path / "schedules.json")
    monkeypatch.setattr("app.services.storage.CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr("app.services.storage.ATTENDANCE_FILE", tmp_path / "attendance.json")
    monkeypatch.setattr("app.services.storage.CALENDAR_FILE", tmp_path / "calendar.json")
    monkeypatch.setattr("app.services.storage.LOCKS_DIR", tmp_path / ".locks")
    _ensure_data_dir()
    return tmp_path


class TestLoadSaveJson:
    def test_load_nonexistent_returns_empty(self, setup_test_data):
        result = _load_json(setup_test_data / "nonexistent.json")
        assert result == {}

    def test_save_and_load(self, setup_test_data):
        data = {"key": "value", "number": 42}
        _save_json(setup_test_data / "test.json", data)
        loaded = _load_json(setup_test_data / "test.json")
        assert loaded == data

    def test_load_invalid_json(self, setup_test_data):
        f = setup_test_data / "bad.json"
        f.write_text("not valid json{{{")
        result = _load_json(f)
        assert result == {}


class TestSchedules:
    def test_get_schedules_empty(self):
        assert get_schedules() == []

    def test_save_and_get(self):
        schedule = {"name": "Test", "work_blocks": [{"entry": "09:00", "exit": "17:00"}]}
        saved = save_schedule(schedule)
        assert "id" in saved
        assert saved["name"] == "Test"
        assert len(get_schedules()) == 1

    def test_get_schedule_by_id(self):
        schedule = {"name": "Test"}
        saved = save_schedule(schedule)
        result = get_schedule(saved["id"])
        assert result is not None
        assert result["name"] == "Test"

    def test_get_schedule_not_found(self):
        assert get_schedule("nonexistent") is None

    def test_update_schedule(self):
        schedule = {"name": "Original"}
        saved = save_schedule(schedule)
        saved["name"] = "Updated"
        updated = save_schedule(saved)
        assert updated["name"] == "Updated"
        assert len(get_schedules()) == 1

    def test_delete_schedule(self):
        schedule = {"name": "To Delete"}
        saved = save_schedule(schedule)
        assert len(get_schedules()) == 1
        delete_schedule(saved["id"])
        assert len(get_schedules()) == 0


class TestConfig:
    def test_get_config_empty(self):
        assert get_config() == {}

    def test_save_and_get(self):
        config = {"holded_email": "test@example.com"}
        saved = save_config(config)
        assert saved["holded_email"] == "test@example.com"
        assert "updated_at" in saved


class TestAttendance:
    def test_get_attendance_empty(self):
        assert get_attendance() == []

    def test_save_and_get(self):
        log = {"date": "2026-01-15", "status": "completed", "total_hours": 8.0}
        saved = save_attendance(log)
        assert "id" in saved
        assert saved["date"] == "2026-01-15"
        assert len(get_attendance()) == 1

    def test_upsert_by_date(self):
        log1 = {"date": "2026-01-15", "status": "in_progress"}
        save_attendance(log1)
        log2 = {"date": "2026-01-15", "status": "completed", "exit_time": "17:00"}
        save_attendance(log2)
        logs = get_attendance()
        assert len(logs) == 1
        assert logs[0]["status"] == "completed"
        assert logs[0]["exit_time"] == "17:00"

    def test_filter_by_date_range(self):
        save_attendance({"date": "2026-01-10", "status": "completed"})
        save_attendance({"date": "2026-01-15", "status": "completed"})
        save_attendance({"date": "2026-01-20", "status": "completed"})

        logs = get_attendance(start_date="2026-01-12", end_date="2026-01-18")
        assert len(logs) == 1
        assert logs[0]["date"] == "2026-01-15"

    def test_delete_attendance(self):
        log = save_attendance({"date": "2026-01-15", "status": "completed"})
        assert len(get_attendance()) == 1
        delete_attendance(log["id"])
        assert len(get_attendance()) == 0


class TestCalendar:
    def test_get_events_empty(self):
        assert get_calendar_events() == []

    def test_save_and_get(self):
        event = {"event_date": "2026-12-25", "event_type": "holiday", "description": "Christmas"}
        saved = save_calendar_event(event)
        assert "id" in saved
        assert len(get_calendar_events()) == 1

    def test_filter_by_month(self):
        save_calendar_event({"event_date": "2026-01-15", "event_type": "holiday"})
        save_calendar_event({"event_date": "2026-02-20", "event_type": "vacation"})
        events = get_calendar_events(year=2026, month=1)
        assert len(events) == 1

    def test_delete_event(self):
        event = save_calendar_event({"event_date": "2026-01-15", "event_type": "holiday"})
        delete_calendar_event(event["id"])
        assert len(get_calendar_events()) == 0
