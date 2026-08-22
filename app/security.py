"""Authentication and security module for API and Web Dashboard."""
import hmac
import hashlib
import time
from typing import Optional, Tuple
from fastapi import Request, Security, HTTPException, status, Depends
from fastapi.security import APIKeyHeader

from app.config import settings
from app.services.storage import get_config

SESSION_COOKIE_NAME = "autoholded_session"
SESSION_MAX_AGE = 86400 * 7  # 7 days

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_dashboard_credentials() -> Tuple[str, Optional[str]]:
    """Get dashboard username and password from config.json or settings."""
    try:
        cfg = get_config()
        username = cfg.get("dashboard_username") or settings.DASHBOARD_USERNAME or "admin"
        password = cfg.get("dashboard_password") or settings.DASHBOARD_PASSWORD
        return username, password
    except Exception:
        return settings.DASHBOARD_USERNAME or "admin", settings.DASHBOARD_PASSWORD


def is_dashboard_auth_enabled() -> bool:
    """Check if dashboard authentication is enabled."""
    _, password = get_dashboard_credentials()
    return bool(password)


def create_session_token(username: str) -> str:
    """Create a signed session token."""
    timestamp = str(int(time.time()))
    secret = settings.SECRET_KEY.encode('utf-8')
    data = f"{username}:{timestamp}".encode('utf-8')
    sig = hmac.new(secret, data, hashlib.sha256).hexdigest()
    return f"{username}:{timestamp}:{sig}"


def verify_session_token(token: str) -> bool:
    """Verify a signed session token."""
    if not token or ":" not in token:
        return False
    try:
        parts = token.split(":")
        if len(parts) != 3:
            return False
        username, timestamp_str, sig = parts
        timestamp = int(timestamp_str)

        # Check expiry (7 days)
        if time.time() - timestamp > SESSION_MAX_AGE:
            return False

        expected_user, expected_pass = get_dashboard_credentials()
        if not expected_pass or username != expected_user:
            return False

        secret = settings.SECRET_KEY.encode('utf-8')
        data = f"{username}:{timestamp_str}".encode('utf-8')
        expected_sig = hmac.new(secret, data, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected_sig)
    except Exception:
        return False


def is_web_authenticated(request: Request) -> bool:
    """Check if the web request has a valid dashboard session."""
    if not is_dashboard_auth_enabled():
        return True
    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie and verify_session_token(cookie):
        return True
    return False


async def verify_api_key(
    request: Request,
    api_key: Optional[str] = Security(api_key_header)
):
    """
    Verify API access.
    Allows access if:
    1. Neither API_KEY nor DASHBOARD_PASSWORD is configured
    2. Valid X-API-Key header matches settings.API_KEY
    3. Valid autoholded_session cookie is present from web login
    """
    _, dash_pass = get_dashboard_credentials()

    # If neither API_KEY nor DASHBOARD_PASSWORD is set, allow access
    if not settings.API_KEY and not dash_pass:
        return True

    # Check X-API-Key header if API_KEY is set
    if settings.API_KEY and api_key == settings.API_KEY:
        return True

    # Check session cookie (allows web dashboard JS fetch calls)
    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie and verify_session_token(cookie):
        return True

    # If API_KEY is configured but invalid/missing and no valid session cookie
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No autorizado: Se requiere API Key válida o inicio de sesión en el Dashboard"
    )
