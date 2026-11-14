import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

app.include_router(router)