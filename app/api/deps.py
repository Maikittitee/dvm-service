from typing import Optional
from app.core.vmc_controller import VendingMachineController
from app.services.dispense_service import DispenseService

_vmc_controller: Optional[VendingMachineController] = None
_dispense_service: Optional[DispenseService] = None


def init_services(controller: VendingMachineController):
    global _vmc_controller, _dispense_service
    _vmc_controller = controller
    _dispense_service = DispenseService(controller)


def get_vmc_controller() -> Optional[VendingMachineController]:
    return _vmc_controller


def get_dispense_service() -> Optional[DispenseService]:
    return _dispense_service


def cleanup_services():
    global _vmc_controller, _dispense_service
    if _vmc_controller:
        _vmc_controller.disconnect()
    _vmc_controller = None
    _dispense_service = None
