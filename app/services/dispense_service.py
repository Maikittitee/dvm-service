import asyncio
import logging
import uuid
from typing import Optional

from app.core.vmc_controller import (
    VendingMachineController,
    DispenseResult,
    DispensingStatus,
    AisleStatus,
)
from app.schemas.dispense import (
    DispenseRequest,
    DispenseResponse,
    DispenseStatusEnum,
    AisleStatusResponse,
    AisleStatusEnum,
)

logger = logging.getLogger(__name__)


class DispenseService:
    def __init__(self, controller: VendingMachineController):
        self.controller = controller
        self._pending_dispenses: dict[int, asyncio.Future] = {}
        self._pending_status_checks: dict[int, asyncio.Future] = {}

    def _map_dispense_status(self, status: DispensingStatus) -> DispenseStatusEnum:
        mapping = {
            DispensingStatus.DISPENSING: DispenseStatusEnum.DISPENSING,
            DispensingStatus.SUCCESS: DispenseStatusEnum.SUCCESS,
            DispensingStatus.JAMMED: DispenseStatusEnum.JAMMED,
            DispensingStatus.MOTOR_DOESNT_STOP: DispenseStatusEnum.MOTOR_ERROR,
            DispensingStatus.MOTOR_DOESNT_EXIST: DispenseStatusEnum.NOT_FOUND,
        }
        return mapping.get(status, DispenseStatusEnum.FAILED)

    def _map_aisle_status(self, status: AisleStatus) -> AisleStatusEnum:
        mapping = {
            AisleStatus.NORMAL: AisleStatusEnum.NORMAL,
            AisleStatus.OUT_OF_STOCK: AisleStatusEnum.OUT_OF_STOCK,
            AisleStatus.DOESNT_EXIST: AisleStatusEnum.NOT_EXIST,
            AisleStatus.PAUSED: AisleStatusEnum.PAUSED,
        }
        return mapping.get(status, AisleStatusEnum.NOT_EXIST)

    async def dispense(
        self, request: DispenseRequest, timeout: float = 30.0
    ) -> DispenseResponse:
        if not self.controller.is_connected:
            return DispenseResponse(
                success=False,
                aisle_number=request.aisle_number,
                status=DispenseStatusEnum.FAILED,
                message="VMC not connected",
            )

        transaction_id = f"txn_{uuid.uuid4().hex[:12]}"
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()

        def on_dispense_result(result: DispenseResult):
            if not future.done():
                loop.call_soon_threadsafe(future.set_result, result)

        self._pending_dispenses[request.aisle_number] = future

        try:
            if request.force:
                logger.info(f"Force dispensing aisle {request.aisle_number}")
                self.controller.drive_aisle_direct(
                    aisle_number=request.aisle_number,
                    use_drop_sensor=request.use_drop_sensor,
                    use_elevator=request.use_elevator,
                    callback=on_dispense_result,
                )
            else:
                self.controller.dispense(
                    aisle_number=request.aisle_number,
                    callback=on_dispense_result,
                )

            result: DispenseResult = await asyncio.wait_for(future, timeout=timeout)

            return DispenseResponse(
                success=result.success,
                aisle_number=result.aisle_number,
                status=self._map_dispense_status(result.status),
                message=result.message,
                transaction_id=transaction_id,
            )

        except asyncio.TimeoutError:
            logger.warning(
                f"Dispense timeout for aisle {request.aisle_number} "
                f"(transaction: {transaction_id})"
            )
            return DispenseResponse(
                success=False,
                aisle_number=request.aisle_number,
                status=DispenseStatusEnum.FAILED,
                message="Operation timed out",
                transaction_id=transaction_id,
            )

        except Exception as e:
            logger.error(f"Dispense error: {e}")
            return DispenseResponse(
                success=False,
                aisle_number=request.aisle_number,
                status=DispenseStatusEnum.FAILED,
                message=str(e),
                transaction_id=transaction_id,
            )

        finally:
            self._pending_dispenses.pop(request.aisle_number, None)

    async def check_aisle_status(
        self, aisle_number: int, timeout: float = 10.0
    ) -> AisleStatusResponse:
        if not self.controller.is_connected:
            return AisleStatusResponse(
                aisle_number=aisle_number,
                status=AisleStatusEnum.NOT_EXIST,
                message="VMC not connected",
            )

        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()

        def on_status_result(aisle_num: int, status: AisleStatus):
            if not future.done():
                loop.call_soon_threadsafe(future.set_result, (aisle_num, status))

        self._pending_status_checks[aisle_number] = future

        try:
            self.controller.check_aisle(
                aisle_number=aisle_number,
                callback=on_status_result,
            )

            aisle_num, status = await asyncio.wait_for(future, timeout=timeout)

            status_messages = {
                AisleStatus.NORMAL: "Aisle is ready",
                AisleStatus.OUT_OF_STOCK: "Aisle is out of stock",
                AisleStatus.DOESNT_EXIST: "Aisle does not exist",
                AisleStatus.PAUSED: "Aisle is paused",
            }

            return AisleStatusResponse(
                aisle_number=aisle_num,
                status=self._map_aisle_status(status),
                message=status_messages.get(status, "Unknown status"),
            )

        except asyncio.TimeoutError:
            logger.warning(f"Aisle status check timeout for aisle {aisle_number}")
            return AisleStatusResponse(
                aisle_number=aisle_number,
                status=AisleStatusEnum.NOT_EXIST,
                message="Status check timed out",
            )

        except Exception as e:
            logger.error(f"Aisle status check error: {e}")
            return AisleStatusResponse(
                aisle_number=aisle_number,
                status=AisleStatusEnum.NOT_EXIST,
                message=str(e),
            )

        finally:
            self._pending_status_checks.pop(aisle_number, None)
