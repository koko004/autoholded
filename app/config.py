"""Application configuration."""
from pydantic_settings import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Application
    APP_NAME: str = "Fichador Holded"
    APP_VERSION: str = "1.3.0"
    DEBUG: bool = False
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/fichador.db"
    
    # Security
    SECRET_KEY: str = "change-this-to-a-random-secret-key"
    API_KEY: Optional[str] = None
    
    # Timezone
    TZ: str = "Europe/Madrid"
    
    # Holded
    HOLDED_EMAIL: Optional[str] = None
    HOLDED_PASSWORD: Optional[str] = None
    HOLDED_URL: str = "https://app.holded.com/myzone"
    
    # Notifications - Email
    SMTP_ENABLED: bool = False
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM: Optional[str] = None
    
    # Notifications - Webhook
    WEBHOOK_ENABLED: bool = False
    WEBHOOK_URL: Optional[str] = None
    
    # Scheduler
    SCHEDULER_TIMEZONE: str = "Europe/Madrid"
    FICHAJE_TIMEOUT: int = 300  # 5 minutes max per fichaje
    MAX_RETRIES: int = 3
    
    # Playwright
    HEADLESS: bool = True
    BROWSER_TIMEOUT: int = 60000  # 60 seconds
    CHROMIUM_URL: Optional[str] = None
    
    # Telegram Bot
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_CHAT_ID: Optional[str] = None
    TELEGRAM_ENABLED: bool = False
    TELEGRAM_SCREENSHOT_MODE: str = "last"  # "all", "last", "summary"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


settings = Settings()
