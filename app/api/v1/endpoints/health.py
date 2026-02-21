from fastapi import APIRouter
from app.schemas.dispense import HealthResponse
from app.api.deps import get_vmc_controller
from app.config import get_settings

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    settings = get_settings()
    controller = get_vmc_controller()

    return HealthResponse(
        status="healthy",
        vmc_connected=controller.is_connected if controller else False,
        serial_port=settings.serial_port,
    )


@router.get("/ready")
async def readiness_check() -> dict:
    controller = get_vmc_controller()
    is_ready = controller is not None and controller.is_connected

    return {
        "ready": is_ready,
        "message": "Service ready" if is_ready else "VMC not connected",
    }
