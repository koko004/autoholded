"""FastAPI application entry point."""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

from app.config import settings
from app.routers import api, web

# Configure logging
Path("logs").mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/app.log", encoding="utf-8")
    ]
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    print(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")

    # Ensure data directory exists
    from pathlib import Path
    Path("data").mkdir(parents=True, exist_ok=True)

    # Auto-start scheduler
    from app.services.scheduler import scheduler
    try:
        await scheduler.start()
        print("Scheduler auto-started")
    except Exception as e:
        print(f"Failed to auto-start scheduler: {e}")

    # Auto-start Telegram bot if configured
    from app.services.telegram_bot import telegram_bot
    try:
        from app.services.storage import get_config
        tg_config = get_config()
        tg_token = tg_config.get("telegram_token") or settings.TELEGRAM_BOT_TOKEN
        tg_chat_id = tg_config.get("telegram_chat_id") or settings.TELEGRAM_CHAT_ID
        tg_enabled = tg_config.get("telegram_enabled", settings.TELEGRAM_ENABLED)
        tg_mode = tg_config.get("telegram_screenshot_mode", settings.TELEGRAM_SCREENSHOT_MODE)

        if tg_enabled and tg_token and tg_chat_id:
            telegram_bot.configure(tg_token, tg_chat_id, tg_mode)
            await telegram_bot.start()
            print("Telegram bot auto-started")
    except Exception as e:
        print(f"Failed to auto-start Telegram bot: {e}")

    yield

    # Shutdown
    from app.services.scheduler import scheduler
    try:
        await scheduler.stop()
    except:
        pass

    from app.services.telegram_bot import telegram_bot
    try:
        await telegram_bot.stop()
    except:
        pass

    print("Shutting down...")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Automatización de fichaje para Holded",
    lifespan=lifespan
)

# Mount static files
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

# Include routers
app.include_router(api.router, prefix="/api")
app.include_router(web.router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
