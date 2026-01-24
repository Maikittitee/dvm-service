from fastapi import APIRouter, HTTPException, status
from app.schemas.dispense import (
    DispenseRequest,
    DispenseResponse,
    AisleStatusResponse,
    ErrorResponse,
)
from app.api.deps import get_dispense_service

router = APIRouter()


@router.post(
    "/dispense",
    response_model=DispenseResponse,
    responses={
        200: {"description": "Dispense operation completed"},
        503: {"model": ErrorResponse, "description": "VMC not available"},
    },
)
async def dispense_product(request: DispenseRequest) -> DispenseResponse:
    service = get_dispense_service()
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="VMC service not initialized",
        )

    response = await service.dispense(request)
    return response


@router.get(
    "/aisle/{aisle_number}/status",
    response_model=AisleStatusResponse,
    responses={
        200: {"description": "Aisle status retrieved"},
        503: {"model": ErrorResponse, "description": "VMC not available"},
    },
)
async def get_aisle_status(aisle_number: int) -> AisleStatusResponse:
    service = get_dispense_service()
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="VMC service not initialized",
        )

    response = await service.check_aisle_status(aisle_number)
    return response


@router.post(
    "/aisle/{aisle_number}/dispense",
    response_model=DispenseResponse,
    responses={
        200: {"description": "Dispense operation completed"},
        503: {"model": ErrorResponse, "description": "VMC not available"},
    },
)
async def dispense_from_aisle(
    aisle_number: int,
    force: bool = False,
) -> DispenseResponse:
    request = DispenseRequest(aisle_number=aisle_number, force=force)
    service = get_dispense_service()
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="VMC service not initialized",
        )

    response = await service.dispense(request)
    return response
