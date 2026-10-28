"""FastAPI Application entrypoint, CORS configuration, and router registration."""

from contextlib import asynccontextmanager
import logging
import time
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.chat import router as chat_router
from app.api.connections import router as connections_router
from app.core.config import get_settings
from app.db.manager import get_connection_manager
from app.db.seed_demo import register_demo_connection_if_needed

# Configure logging format
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifecycle events (startup and shutdown)."""
    settings = get_settings()
    logger.info("Starting %s v%s...", settings.PROJECT_NAME, settings.VERSION)

    # Auto-seed and register demo database if configured
    try:
        demo_id = register_demo_connection_if_needed()
        if demo_id:
            logger.info("Default demo database ready and registered as '%s'.", demo_id)
    except Exception as exc:
        logger.warning("Could not auto-seed demo database on startup: %s", exc)

    yield

    logger.info("Shutting down %s. Disposing all active database engine pools...", settings.PROJECT_NAME)
    get_connection_manager().close_all()


def create_application() -> FastAPI:
    """Build and configure the main FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description="Production Self-Healing Text-to-SQL Analytics Platform powered by Groq and LangGraph.",
        lifespan=lifespan,
    )

    # Request Timing and Diagnostic Logging Middleware
    @app.middleware("http")
    async def add_process_time_and_logging_middleware(request: Request, call_next):
        start_time = time.perf_counter()
        response = await call_next(request)
        process_time_ms = (time.perf_counter() - start_time) * 1000
        response.headers["X-Process-Time-Ms"] = f"{process_time_ms:.2f}"
        logger.info(
            "%s %s -> status %d (%.2f ms)",
            request.method,
            request.url.path,
            response.status_code,
            process_time_ms,
        )
        return response

    # Configure CORS for Next.js frontend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register API v1 Routers
    app.include_router(connections_router, prefix=settings.API_V1_STR)
    app.include_router(chat_router, prefix=settings.API_V1_STR)

    # Health Check & Root Endpoints
    @app.get("/health", tags=["System"])
    def health_check():
        return {
            "status": "healthy",
            "version": settings.VERSION,
            "project": settings.PROJECT_NAME,
        }

    @app.get("/", tags=["System"])
    def root():
        return {
            "message": "Welcome to Self-Healing Text-to-SQL Analytics API",
            "docs_url": "/docs",
            "version": settings.VERSION,
        }

    # Global Exception Handlers
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled server exception at %s: %s", request.url.path, exc, exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": f"Internal server error: {str(exc)}",
                "path": request.url.path,
            },
        )

    return app


app = create_application()
