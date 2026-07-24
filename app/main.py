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
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
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

    yield

    # Shutdown
    from app.services.scheduler import scheduler
    try:
        await scheduler.stop()
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
