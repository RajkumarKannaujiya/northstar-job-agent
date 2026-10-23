import logging
import time
from contextlib import asynccontextmanager
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.responses import PlainTextResponse
from sqlalchemy import text

from app.api.routes import router
from app.core.config import settings
from app.core.database import Base, engine
from app.core.logging import configure_logging
from app.core.metrics import increment, render_metrics
import app.models  # noqa: F401 - registers tables with SQLAlchemy metadata

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.validate_production_secrets()
    if settings.environment == "development":
        Base.metadata.create_all(bind=engine)
    logger.info("api_started environment=%s", settings.environment)
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", description="Job discovery, matching, and safe application tracking API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])

# A small per-process development guard. Production deployments should also enforce limits at the edge.
_requests: dict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def request_limit(request: Request, call_next):
    address = request.client.host if request.client else "unknown"
    now = time.monotonic()
    bucket = _requests[address]
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= 180:
        return JSONResponse(status_code=429, content={"detail": "Request rate limit exceeded"})
    bucket.append(now)
    increment("http_requests_total")
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


app.include_router(router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok", "environment": settings.environment, "automation": "read_only_company_career_discovery_and_manual_applications"}


@app.get("/ready")
def ready():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        logger.exception("readiness_check_failed")
        return JSONResponse(status_code=503, content={"status": "not_ready", "database": "unavailable"})
    return {"status": "ready", "database": "ok"}


@app.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
def metrics():
    return render_metrics()
