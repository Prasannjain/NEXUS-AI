"""NEXUS AI - FastAPI application entry point."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import approvals, audit, auth, catalog, dashboard, reports, settings as settings_api, workflows
from .config import settings
from .graph.orchestrator import STAGES
from .seed import bootstrap

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("nexus-ai")

DESCRIPTION = """
**NEXUS AI - Autonomous AI Agents for Enterprise Operations**

A multi-agent enterprise automation platform. A natural-language business request
is planned by the Planner Agent, routed through a LangGraph orchestrator to the
specialised HR, Document, IT, Finance and Customer Support agents, gated by human
approval checkpoints for sensitive actions, executed against simulated enterprise
integrations through an authorising tool registry, and recorded in an append-only
audit trail before the final report is produced.

All enterprise integrations in this build are **simulated sandboxes**. No production
system is contacted.

### Getting started
1. `POST /api/auth/login` with a seeded account (see `README.md`).
2. `POST /api/workflows` with a natural-language request.
3. `GET /api/workflows/{id}` to watch the LangGraph stages advance.
4. `GET /api/approvals?status=pending` then `POST /api/approvals/{id}/decide`.
5. `GET /api/workflows/{id}/report.md` for the downloadable execution report.
"""

@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap()
    logger.info(
        "NEXUS AI %s ready | provider=%s | database=%s | redis=%s",
        __version__,
        settings.resolved_llm_provider(),
        settings.database_url.split("://", 1)[0],
        "enabled" if settings.redis_enabled else "disabled",
    )
    yield


app = FastAPI(
    title="NEXUS AI API",
    version=__version__,
    description=DESCRIPTION,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    return JSONResponse(
        status_code=422,
        content={
            "detail": "; ".join(
                f"{'.'.join(str(part) for part in error['loc'][1:])}: {error['msg']}"
                for error in exc.errors()[:5]
            ),
            "field": ".".join(str(part) for part in first.get("loc", [])[1:]),
        },
    )


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    detail = str(exc) if settings.debug else "Internal server error"
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"detail": detail})


@app.get("/api/health", tags=["platform"])
def health() -> dict[str, object]:
    from sqlalchemy import text

    from .database import engine
    from .graph import runtime

    database_ok = True
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        database_ok = False
    return {
        "status": "ok" if database_ok else "degraded",
        "version": __version__,
        "environment": settings.environment,
        "database": "connected" if database_ok else "unreachable",
        "database_dialect": engine.dialect.name,
        "llm_provider": settings.resolved_llm_provider(),
        "orchestrator": "LangGraph",
        "active_workflow_runs": runtime.active_run_count(),
        "simulated_integrations": True,
    }


@app.get("/api/architecture", tags=["platform"])
def architecture() -> dict[str, object]:
    """The twelve-stage reference architecture rendered by the workflow monitor."""
    return {"stages": STAGES}


app.include_router(auth.router)
app.include_router(workflows.router)
app.include_router(approvals.router)
app.include_router(catalog.router)
app.include_router(audit.router)
app.include_router(dashboard.router)
app.include_router(reports.router)
app.include_router(settings_api.router)


# When the React bundle has been built next to this package, serve it from the
# same origin so a single container exposes the whole platform.
_DIST_CANDIDATES = ["../frontend/dist", "frontend/dist", "/app/frontend/dist"]
_dist = next((path for path in _DIST_CANDIDATES if os.path.isdir(path)), None)
if _dist:
    assets = os.path.join(_dist, "assets")
    if os.path.isdir(assets):
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/", include_in_schema=False)
    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str = "") -> FileResponse:
        candidate = os.path.join(_dist, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_dist, "index.html"))
