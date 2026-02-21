from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional


class DispenseStatusEnum(str, Enum):
    PENDING = "pending"
    DISPENSING = "dispensing"
    SUCCESS = "success"
    FAILED = "failed"
    JAMMED = "jammed"
    MOTOR_ERROR = "motor_error"
    NOT_FOUND = "not_found"


class AisleStatusEnum(str, Enum):
    NORMAL = "normal"
    OUT_OF_STOCK = "out_of_stock"
    NOT_EXIST = "not_exist"
    PAUSED = "paused"


class DispenseRequest(BaseModel):
    aisle_number: int = Field(..., ge=1)
    use_drop_sensor: bool = Field(default=True)
    use_elevator: bool = Field(default=False)
    force: bool = Field(default=False)


class DispenseResponse(BaseModel):
    success: bool
    aisle_number: int
    status: DispenseStatusEnum
    message: str
    transaction_id: Optional[str] = None


class AisleStatusResponse(BaseModel):
    aisle_number: int
    status: AisleStatusEnum
    message: str


class HealthResponse(BaseModel):
    status: str
    vmc_connected: bool
    serial_port: str


class ErrorResponse(BaseModel):
    error: str
    message: str
    detail: Optional[str] = None
