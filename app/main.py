import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.api.v1.router import api_router
from app.api.deps import init_services, cleanup_services
from app.core.vmc_controller import VendingMachineController

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info(f"Starting DVM Service v{settings.app_version}")

    controller = VendingMachineController(
        port=settings.serial_port,
        baudrate=settings.serial_baudrate,
        timeout=settings.serial_timeout,
        max_retries=settings.vmc_max_retries,
    )

    if controller.connect():
        controller.start()
        init_services(controller)
        logger.info("VMC controller initialized successfully")
    else:
        init_services(controller)
        logger.warning(
            f"Failed to connect to VMC on {settings.serial_port}. "
            "Service running in disconnected mode."
        )

    yield

    logger.info("Shutting down DVM Service")
    cleanup_services()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="API service for controlling drug vending machines via RS232 protocol.",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.api_prefix)

    @app.get("/", tags=["root"])
    async def root():
        return {
            "service": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
        }

    return app


app = create_app()
