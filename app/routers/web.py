"""Web router for HTML page routes with Dashboard Authentication."""
from fastapi import APIRouter, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from typing import Optional

from app.services.storage import get_config
from app.config import settings
from app.security import (
    is_dashboard_auth_enabled, is_web_authenticated,
    get_dashboard_credentials, create_session_token,
    SESSION_COOKIE_NAME, SESSION_MAX_AGE
)

# Create custom Jinja2 environment with disabled cache to avoid cache key bug
from jinja2 import Environment, FileSystemLoader
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

# Replace the default env with custom one (disable cache for Python 3.13+)
templates.env = Environment(
    loader=FileSystemLoader(Path(__file__).parent.parent / "templates"),
    cache_size=0,  # Disable cache to avoid cache key bug
    autoescape=True
)
templates.env.globals["version"] = settings.APP_VERSION

router = APIRouter()


def render_template(template_name: str, request: Request, context: dict = None):
    """Helper to render Jinja2 templates with common auth context."""
    ctx = {
        "request": request,
        "current_path": request.url.path,
        "auth_enabled": is_dashboard_auth_enabled(),
        "is_logged_in": is_web_authenticated(request)
    }
    if context:
        ctx.update(context)
    # Render directly using the environment to avoid TemplateResponse issues
    template = templates.env.get_template(template_name)
    rendered = template.render(ctx)
    return HTMLResponse(content=rendered)


def check_auth_or_redirect(request: Request) -> Optional[RedirectResponse]:
    """Redirect to /login if dashboard auth is required and user is not authenticated."""
    if is_dashboard_auth_enabled() and not is_web_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    return None


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page for web dashboard."""
    if is_web_authenticated(request) and is_dashboard_auth_enabled():
        return RedirectResponse(url="/", status_code=303)
    return render_template("login.html", request)


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form("")
):
    """Process login form submission."""
    expected_user, expected_pass = get_dashboard_credentials()

    if not expected_pass or (username == expected_user and password == expected_pass):
        token = create_session_token(username)
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=token,
            max_age=SESSION_MAX_AGE,
            httponly=True,
            samesite="lax"
        )
        return response

    return render_template("login.html", request, {
        "error": "Usuario o contraseña incorrectos",
        "username": username
    })


@router.get("/logout")
async def logout_page():
    """Clear session cookie and redirect to login."""
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key=SESSION_COOKIE_NAME)
    return response


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page."""
    redirect = check_auth_or_redirect(request)
    if redirect:
        return redirect
    return render_template("dashboard.html", request)


@router.get("/config", response_class=HTMLResponse)
async def config_page(request: Request):
    """Configuration page."""
    redirect = check_auth_or_redirect(request)
    if redirect:
        return redirect
    config = get_config()
    return render_template("config.html", request, {"config": config})


@router.get("/schedules", response_class=HTMLResponse)
async def schedules_page(request: Request):
    """Work schedules page."""
    redirect = check_auth_or_redirect(request)
    if redirect:
        return redirect
    return render_template("schedules.html", request)


@router.get("/calendar", response_class=HTMLResponse)
async def calendar_page(request: Request):
    """Calendar page."""
    redirect = check_auth_or_redirect(request)
    if redirect:
        return redirect
    return render_template("calendar.html", request)


@router.get("/attendance", response_class=HTMLResponse)
async def attendance_page(request: Request):
    """Attendance history page."""
    redirect = check_auth_or_redirect(request)
    if redirect:
        return redirect
    return render_template("attendance.html", request)


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    """System logs page."""
    redirect = check_auth_or_redirect(request)
    if redirect:
        return redirect
    return render_template("logs.html", request)


@router.get("/debug", response_class=HTMLResponse)
async def debug_page(request: Request):
    """Debug page - shows Playwright screenshots from last operation."""
    redirect = check_auth_or_redirect(request)
    if redirect:
        return redirect
    return render_template("debug.html", request)
