"""Web router for HTML page routes."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from app.services.storage import get_config

templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page."""
    return templates.TemplateResponse(request, "dashboard.html")


@router.get("/config", response_class=HTMLResponse)
async def config_page(request: Request):
    """Configuration page."""
    config = get_config()
    return templates.TemplateResponse(request, "config.html", {"config": config})


@router.get("/schedules", response_class=HTMLResponse)
async def schedules_page(request: Request):
    """Work schedules page."""
    return templates.TemplateResponse(request, "schedules.html")


@router.get("/calendar", response_class=HTMLResponse)
async def calendar_page(request: Request):
    """Calendar page."""
    return templates.TemplateResponse(request, "calendar.html")


@router.get("/attendance", response_class=HTMLResponse)
async def attendance_page(request: Request):
    """Attendance history page."""
    return templates.TemplateResponse(request, "attendance.html")


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    """System logs page."""
    return templates.TemplateResponse(request, "logs.html")


@router.get("/debug", response_class=HTMLResponse)
async def debug_page(request: Request):
    """Debug page - shows Playwright screenshots from last operation."""
    return templates.TemplateResponse(request, "debug.html")
