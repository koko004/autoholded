"""Web router for HTML page routes with Dashboard Authentication."""
from fastapi import APIRouter, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from typing import Optional

from app.services.storage import get_config, save_config
from app.config import settings
from app.security import (
    is_dashboard_auth_enabled, is_web_authenticated, is_first_run,
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
    """Redirect to /login if dashboard auth is required and user is not authenticated.
    
    Also redirects to /setup if no password has been configured yet.
    """
    # First run: force password setup
    if is_first_run():
        if request.url.path != "/setup":
            return RedirectResponse(url="/setup", status_code=303)
        return None

    if is_dashboard_auth_enabled() and not is_web_authenticated(request):
        if request.url.path != "/login":
            return RedirectResponse(url="/login", status_code=303)
        return None
    return None


# === First-run setup ===

@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    """First-run setup page to create admin password."""
    # If already authenticated or password already set, redirect to dashboard
    if not is_first_run():
        if is_web_authenticated(request):
            return RedirectResponse(url="/", status_code=303)
        return RedirectResponse(url="/login", status_code=303)
    return render_template("setup.html", request)


@router.post("/setup")
async def setup_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    """Process first-run setup form."""
    if not username or not password:
        return render_template("setup.html", request, {
            "error": "Usuario y contraseña son obligatorios"
        })

    if len(password) < 4:
        return render_template("setup.html", request, {
            "error": "La contraseña debe tener al menos 4 caracteres",
            "username": username
        })

    # Save to config.json
    cfg = get_config()
    cfg["dashboard_username"] = username
    cfg["dashboard_password"] = password
    save_config(cfg)

    # Also save to .env for persistence
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        env_content = env_path.read_text()
        lines = env_content.split("\n")
        new_lines = []
        found_user = False
        found_pass = False
        for line in lines:
            if line.startswith("DASHBOARD_USERNAME="):
                new_lines.append(f"DASHBOARD_USERNAME={username}")
                found_user = True
            elif line.startswith("DASHBOARD_PASSWORD="):
                new_lines.append(f"DASHBOARD_PASSWORD={password}")
                found_pass = True
            else:
                new_lines.append(line)
        if not found_user:
            new_lines.append(f"DASHBOARD_USERNAME={username}")
        if not found_pass:
            new_lines.append(f"DASHBOARD_PASSWORD={password}")
        env_path.write_text("\n".join(new_lines))

    # Auto-login after setup
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


# === Login / Logout ===

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


# === Protected pages ===

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
