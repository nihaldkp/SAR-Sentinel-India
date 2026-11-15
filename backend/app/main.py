import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.services.acquisitions import (
    automatic_acquisition_enabled,
    automatic_refresh_loop,
)
from app.services.acquisition_jobs import recover_interrupted_jobs
from app.services.integration import (
    configure_processing_adapters,
    recover_interrupted_jobs as recover_interrupted_integration_jobs,
)
from app.services.sar_adapter import NisarGcovAdapter
from app.api.routes import router


LOGGER = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    recover_interrupted_jobs()

    # Register the SAR processor before recovering integration jobs.
    configure_processing_adapters(sar=NisarGcovAdapter())
    recover_interrupted_integration_jobs()

    task = None
    if automatic_acquisition_enabled():
        task = asyncio.create_task(
            automatic_refresh_loop(),
            name="satellite-acquisition",
        )
        LOGGER.info(
            "Automatic satellite catalog discovery and processing enabled"
        )

    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="SAR Sentinel India API",
    description=(
        "SAR Sentinel India API. Dashboard previews and static observations are "
        "demonstrations; the automatic satellite catalog separately records real "
        "acquisitions and explicitly unvalidated candidate processing outputs."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.state.public_read_only = os.getenv("SAR_PUBLIC_READ_ONLY", "false").strip().casefold() == "true"


@app.middleware("http")
async def restrict_public_operations(request: Request, call_next):
    if request.app.state.public_read_only:
        permitted_post = request.method == "POST" and request.url.path in {
            "/api/reports/workspace",
            "/api/sentinel2/comparisons",
            "/api/analysis/ai-summary",
        }
        refresh_requested = (
            request.url.path == "/api/sentinel2/observations"
            and any(value.casefold() not in {"false", "0", "off", "no"}
                    for value in request.query_params.getlist("refresh"))
        )
        if (request.method not in {"GET", "HEAD", "OPTIONS"} and not permitted_post) or refresh_requested:
            return JSONResponse(
                status_code=403,
                content={"detail": "This operation is available only through the private administrative service."},
            )
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("SAR_CORS_ORIGINS", "").split(",") if origin.strip()],
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

app.include_router(router)