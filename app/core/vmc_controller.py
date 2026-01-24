import serial
import time
import threading
import struct
import logging
from enum import Enum
from typing import Optional, Tuple, List, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class Command(Enum):
    POLL = 0x41
    ACK = 0x42
    CHECK_AISLE = 0x01
    AISLE_STATUS_RESPONSE = 0x02
    SELECT_BUY = 0x03
    DISPENSING_STATUS = 0x04
    SELECT_AISLE = 0x05
    DRIVE_AISLE_DIRECT = 0x06
    AISLE_INFO = 0x11
    SET_AISLE_PRICE = 0x12
    SET_AISLE_INVENTORY = 0x13
    SET_AISLE_CAPACITY = 0x14
    SET_AISLE_COMMODITY = 0x15
    POS_DISPLAY = 0x24
    REQUEST_SYNC = 0x31
    REQUEST_MACHINE_STATUS = 0x51
    MACHINE_STATUS_RESPONSE = 0x52


class AisleStatus(Enum):
    NORMAL = 0x01
    OUT_OF_STOCK = 0x02
    DOESNT_EXIST = 0x03
    PAUSED = 0x04


class DispensingStatus(Enum):
    DISPENSING = 0x01
    SUCCESS = 0x02
    JAMMED = 0x03
    MOTOR_DOESNT_STOP = 0x04
    MOTOR_DOESNT_EXIST = 0x06


@dataclass
class DispenseResult:
    success: bool
    aisle_number: int
    status: DispensingStatus
    message: str


@dataclass
class AisleInfo:
    aisle_number: int
    price: int
    inventory: int
    capacity: int
    commodity_number: int
    is_paused: bool


class VendingMachineController:
    STX = bytes([0xFA, 0xFB])
    MAX_RETRIES = 5
    POLL_INTERVAL = 0.2
    COMMAND_TIMEOUT = 1.0

    def __init__(
        self,
        port: str,
        baudrate: int = 57600,
        timeout: float = 0.1,
        max_retries: int = 5,
    ):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.max_retries = max_retries
        self.serial: Optional[serial.Serial] = None
        self.comm_number = 1
        self.running = False
        self.poll_thread: Optional[threading.Thread] = None
        self.command_queue: List[dict] = []
        self.lock = threading.Lock()
        self.dispense_callbacks: dict[int, Callable] = {}
        self.aisle_status_callbacks: dict[int, Callable] = {}
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self.serial is not None and self.serial.is_open

    def connect(self) -> bool:
        try:
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout,
            )
            self._connected = True
            logger.info(f"Connected to vending machine on {self.port}")
            return True
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self._connected = False
            return False

    def disconnect(self):
        self.stop()
        if self.serial and self.serial.is_open:
            self.serial.close()
        self._connected = False
        logger.info("Disconnected from vending machine")

    def calculate_xor(self, data: bytes) -> int:
        xor = 0
        for byte in data:
            xor ^= byte
        return xor

    def create_packet(self, command: Command, text: bytes = b"") -> bytes:
        length = len(text)
        packet = self.STX + bytes([command.value, length]) + text
        xor = self.calculate_xor(packet)
        return packet + bytes([xor])

    def parse_packet(self, data: bytes) -> Optional[Tuple[Command, bytes]]:
        if len(data) < 5:
            return None

        if data[0:2] != self.STX:
            return None

        command_value = data[2]
        length = data[3]

        if len(data) < 5 + length:
            return None

        text = data[4 : 4 + length]
        xor_received = data[4 + length]
        xor_calculated = self.calculate_xor(data[0 : 4 + length])

        if xor_received != xor_calculated:
            logger.warning(
                f"XOR check failed: received {xor_received:02x}, "
                f"calculated {xor_calculated:02x}"
            )
            return None

        try:
            command = Command(command_value)
            return command, text
        except ValueError:
            logger.debug(f"Unknown command: 0x{command_value:02x}")
            return None

    def send_ack(self) -> bool:
        ack_packet = self.create_packet(Command.ACK)
        try:
            self.serial.write(ack_packet)
            return True
        except Exception as e:
            logger.error(f"Failed to send ACK: {e}")
            return False

    def get_next_comm_number(self) -> int:
        current = self.comm_number
        self.comm_number = (self.comm_number % 255) + 1
        return current

    def queue_command(
        self,
        command: Command,
        text: bytes = b"",
        callback: Optional[Callable] = None,
        callback_key: Optional[int] = None,
    ):
        with self.lock:
            packet = self.create_packet(command, text)
            self.command_queue.append(
                {
                    "packet": packet,
                    "command": command,
                    "text": text,
                    "retries": 0,
                    "max_retries": self.max_retries,
                    "waiting_ack": False,
                    "sent_time": None,
                    "callback": callback,
                    "callback_key": callback_key,
                }
            )
            logger.debug(f"Queued command: {command.name}")

    def handle_poll(self):
        with self.lock:
            if self.command_queue and self.command_queue[0].get("waiting_ack"):
                cmd_info = self.command_queue[0]
                if time.time() - cmd_info["sent_time"] > self.COMMAND_TIMEOUT:
                    cmd_info["retries"] += 1
                    if cmd_info["retries"] >= cmd_info["max_retries"]:
                        logger.error(
                            f"Command {cmd_info['command'].name} failed after "
                            f"{cmd_info['max_retries']} retries"
                        )
                        self.command_queue.pop(0)
                    else:
                        cmd_info["waiting_ack"] = False

            if self.command_queue and not self.command_queue[0].get("waiting_ack"):
                cmd_info = self.command_queue[0]
                try:
                    self.serial.write(cmd_info["packet"])
                    cmd_info["waiting_ack"] = True
                    cmd_info["sent_time"] = time.time()
                    logger.debug(
                        f"Sent {cmd_info['command'].name} "
                        f"(attempt {cmd_info['retries'] + 1})"
                    )
                except Exception as e:
                    logger.error(f"Failed to send queued command: {e}")
            else:
                self.send_ack()

    def listen_loop(self):
        buffer = b""

        while self.running:
            try:
                if self.serial.in_waiting > 0:
                    data = self.serial.read(self.serial.in_waiting)
                    buffer += data

                    while len(buffer) >= 5:
                        stx_index = buffer.find(self.STX)
                        if stx_index == -1:
                            buffer = b""
                            break

                        if stx_index > 0:
                            buffer = buffer[stx_index:]

                        if len(buffer) < 5:
                            break

                        length = buffer[3]
                        packet_length = 5 + length

                        if len(buffer) < packet_length:
                            break

                        packet = buffer[:packet_length]
                        buffer = buffer[packet_length:]

                        parsed = self.parse_packet(packet)
                        if parsed:
                            command, text = parsed
                            self.handle_received_packet(command, text)

                time.sleep(0.01)

            except Exception as e:
                logger.error(f"Error in listen loop: {e}")
                time.sleep(0.1)

    def handle_received_packet(self, command: Command, text: bytes):
        if command == Command.POLL:
            self.handle_poll()

        elif command == Command.ACK:
            with self.lock:
                if self.command_queue and self.command_queue[0].get("waiting_ack"):
                    cmd_info = self.command_queue.pop(0)
                    logger.debug(f"Command {cmd_info['command'].name} acknowledged")

        elif command == Command.DISPENSING_STATUS:
            self.handle_dispensing_status(text)
            self.send_ack()

        elif command == Command.AISLE_STATUS_RESPONSE:
            self.handle_aisle_status_response(text)
            self.send_ack()

        elif command == Command.AISLE_INFO:
            self.send_ack()

        elif command == Command.REQUEST_SYNC:
            logger.debug("VMC requests synchronization")
            self.send_ack()
            self.request_info_sync()

        elif command == Command.MACHINE_STATUS_RESPONSE:
            self.send_ack()

        elif command == Command.POS_DISPLAY:
            self.send_ack()

        else:
            self.send_ack()

    def handle_dispensing_status(self, data: bytes):
        if len(data) < 4:
            return

        comm_num = data[0]
        status_code = data[1]
        aisle_num = struct.unpack(">H", data[2:4])[0]

        try:
            status = DispensingStatus(status_code)
        except ValueError:
            status = None

        logger.info(f"Dispensing status for aisle {aisle_num}: {status}")

        if aisle_num in self.dispense_callbacks:
            callback = self.dispense_callbacks.pop(aisle_num)
            if status == DispensingStatus.SUCCESS:
                result = DispenseResult(
                    success=True,
                    aisle_number=aisle_num,
                    status=status,
                    message="Dispense successful",
                )
            elif status == DispensingStatus.DISPENSING:
                self.dispense_callbacks[aisle_num] = callback
                return
            else:
                status_messages = {
                    DispensingStatus.JAMMED: "Product jammed",
                    DispensingStatus.MOTOR_DOESNT_STOP: "Motor error - doesn't stop",
                    DispensingStatus.MOTOR_DOESNT_EXIST: "Motor not found",
                }
                result = DispenseResult(
                    success=False,
                    aisle_number=aisle_num,
                    status=status,
                    message=status_messages.get(status, "Unknown error"),
                )
            callback(result)

    def handle_aisle_status_response(self, data: bytes):
        if len(data) < 4:
            return

        comm_num = data[0]
        status_code = data[1]
        aisle_num = struct.unpack(">H", data[2:4])[0]

        try:
            status = AisleStatus(status_code)
        except ValueError:
            status = None

        logger.info(f"Aisle {aisle_num} status: {status}")

        if aisle_num in self.aisle_status_callbacks:
            callback = self.aisle_status_callbacks.pop(aisle_num)
            callback(aisle_num, status)

    def start(self) -> bool:
        if not self.serial or not self.serial.is_open:
            logger.error("Not connected to vending machine")
            return False

        self.running = True
        self.poll_thread = threading.Thread(target=self.listen_loop, daemon=True)
        self.poll_thread.start()

        time.sleep(0.5)
        self.request_info_sync()
        time.sleep(1)

        logger.info("VMC controller started")
        return True

    def stop(self):
        self.running = False
        if self.poll_thread:
            self.poll_thread.join(timeout=2.0)
        logger.info("VMC controller stopped")

    def request_info_sync(self) -> bool:
        comm_num = self.get_next_comm_number()
        text = bytes([comm_num])
        self.queue_command(Command.REQUEST_SYNC, text)
        return True

    def check_aisle(
        self, aisle_number: int, callback: Optional[Callable] = None
    ) -> bool:
        comm_num = self.get_next_comm_number()
        aisle_bytes = struct.pack(">H", aisle_number)
        text = bytes([comm_num]) + aisle_bytes

        if callback:
            self.aisle_status_callbacks[aisle_number] = callback

        self.queue_command(Command.CHECK_AISLE, text)
        return True

    def dispense(
        self, aisle_number: int, callback: Optional[Callable] = None
    ) -> bool:
        comm_num = self.get_next_comm_number()
        aisle_bytes = struct.pack(">H", aisle_number)
        text = bytes([comm_num]) + aisle_bytes

        if callback:
            self.dispense_callbacks[aisle_number] = callback

        self.queue_command(Command.SELECT_BUY, text)
        logger.info(f"Dispense command queued for aisle {aisle_number}")
        return True

    def drive_aisle_direct(
        self,
        aisle_number: int,
        use_drop_sensor: bool = True,
        use_elevator: bool = False,
        callback: Optional[Callable] = None,
    ) -> bool:
        comm_num = self.get_next_comm_number()
        sensor = 1 if use_drop_sensor else 0
        elevator = 1 if use_elevator else 0
        aisle_bytes = struct.pack(">H", aisle_number)
        text = bytes([comm_num, sensor, elevator]) + aisle_bytes

        if callback:
            self.dispense_callbacks[aisle_number] = callback

        self.queue_command(Command.DRIVE_AISLE_DIRECT, text)
        logger.info(f"Drive direct command queued for aisle {aisle_number}")
        return True

    def set_aisle_inventory(self, aisle_number: int, inventory: int) -> bool:
        comm_num = self.get_next_comm_number()
        aisle_bytes = struct.pack(">H", aisle_number)
        text = bytes([comm_num]) + aisle_bytes + bytes([inventory])
        self.queue_command(Command.SET_AISLE_INVENTORY, text)
        return True

    def request_machine_status(self) -> bool:
        comm_num = self.get_next_comm_number()
        text = bytes([comm_num])
        self.queue_command(Command.REQUEST_MACHINE_STATUS, text)
        return True
