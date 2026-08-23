"""Tests for API endpoints."""
import pytest
from pathlib import Path
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def setup_test_data(tmp_path, monkeypatch):
    """Use a temporary directory for test data."""
    monkeypatch.setattr("app.services.storage.DATA_DIR", tmp_path)
    monkeypatch.setattr("app.services.storage.SCHEDULES_FILE", tmp_path / "schedules.json")
    monkeypatch.setattr("app.services.storage.CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr("app.services.storage.ATTENDANCE_FILE", tmp_path / "attendance.json")
    monkeypatch.setattr("app.services.storage.CALENDAR_FILE", tmp_path / "calendar.json")
    monkeypatch.setattr("app.services.storage.LOCKS_DIR", tmp_path / ".locks")
    Path(tmp_path / ".locks").mkdir(exist_ok=True)
    # Disable auth for tests
    monkeypatch.setattr("app.config.settings.DASHBOARD_PASSWORD", None)
    return tmp_path


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


class TestHealthCheck:
    def test_health(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data


class TestSchedulesAPI:
    def test_get_schedules_empty(self, client):
        response = client.get("/api/schedules")
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.skip(reason="Requires apscheduler dependency")
    def test_create_schedule(self, client):
        schedule = {
            "name": "Horario Test",
            "work_blocks": [{"entry": "09:00", "exit": "17:00"}],
            "is_active": True
        }
        response = client.post("/api/schedules", json=schedule)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Horario Test"
        assert "id" in data

    @pytest.mark.skip(reason="Requires apscheduler dependency")
    def test_create_and_delete_schedule(self, client):
        schedule = {"name": "Para borrar", "work_blocks": [{"entry": "09:00", "exit": "17:00"}]}
        create_resp = client.post("/api/schedules", json=schedule)
        schedule_id = create_resp.json()["id"]

        delete_resp = client.delete(f"/api/schedules/{schedule_id}")
        assert delete_resp.status_code == 200

        get_resp = client.get("/api/schedules")
        assert len(get_resp.json()) == 0

    def test_get_nonexistent_schedule(self, client):
        response = client.get("/api/schedules/nonexistent")
        assert response.status_code == 404


class TestAttendanceAPI:
    def test_get_attendance_empty(self, client):
        response = client.get("/api/attendance")
        assert response.status_code == 200
        assert response.json() == []

    def test_today_status(self, client):
        response = client.get("/api/attendance/today")
        assert response.status_code == 200
        data = response.json()
        assert "current_status" in data


class TestConfigAPI:
    def test_get_config(self, client):
        response = client.get("/api/config")
        assert response.status_code == 200

    def test_get_headless_mode(self, client):
        response = client.get("/api/config/headless")
        assert response.status_code == 200
        assert "headless" in response.json()


class TestCalendarAPI:
    def test_get_calendar_empty(self, client):
        response = client.get("/api/calendar")
        assert response.status_code == 200
        assert response.json() == []


class TestLogsAPI:
    def test_get_logs(self, client):
        response = client.get("/api/logs")
        assert response.status_code == 200


class TestDebugAPI:
    def test_get_debug_steps(self, client):
        response = client.get("/api/debug/steps")
        assert response.status_code == 200
        assert "steps" in response.json()
