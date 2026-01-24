#!/usr/bin/env python3
"""
Vending Machine Upper Computer Controller
Based on JSK Vending Machine Communication Protocol

This implementation allows you to control a vending machine VMC (Vending Machine Controller)
from an upper computer via RS232 serial communication.

Protocol: RS232, 57600 baud, 8 data bits, 1 stop bit, no parity
"""

import serial
import time
import threading
from enum import Enum
from typing import Optional, Tuple, List
import struct


class Command(Enum):
    """Command types for vending machine communication"""
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
    """Aisle status codes"""
    NORMAL = 0x01
    OUT_OF_STOCK = 0x02
    DOESNT_EXIST = 0x03
    PAUSED = 0x04


class DispensingStatus(Enum):
    """Dispensing status codes"""
    DISPENSING = 0x01
    SUCCESS = 0x02
    JAMMED = 0x03
    MOTOR_DOESNT_STOP = 0x04
    MOTOR_DOESNT_EXIST = 0x06


class VendingMachineController:
    """Upper Computer controller for vending machine"""

    STX = bytes([0xFA, 0xFB])
    MAX_RETRIES = 5
    POLL_INTERVAL = 0.2  # 200ms
    COMMAND_TIMEOUT = 0.1  # 100ms

    def __init__(self, port: str, baudrate: int = 57600, verbose: bool = False):
        """
        Initialize the vending machine controller

        Args:
            port: Serial port name (e.g., 'COM3' on Windows, '/dev/ttyUSB0' on Linux)
            baudrate: Communication baud rate (default: 57600)
            verbose: Enable verbose output (default: False)
        """
        self.port = port
        self.baudrate = baudrate
        self.verbose = verbose
        self.serial: Optional[serial.Serial] = None
        self.comm_number = 1  # Communication number (1-255)
        self.running = False
        self.poll_thread: Optional[threading.Thread] = None
        self.command_queue: List[bytes] = []
        self.response_callback = None
        self.lock = threading.Lock()
        self.suppress_unsolicited = True  # Suppress unsolicited messages from VMC

    def connect(self) -> bool:
        """
        Connect to the vending machine

        Returns:
            bool: True if connection successful
        """
        try:
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.1
            )
            print(f"Connected to vending machine on {self.port}")
            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            return False

    def disconnect(self):
        """Disconnect from the vending machine"""
        self.stop()
        if self.serial and self.serial.is_open:
            self.serial.close()
            print("Disconnected from vending machine")

    def calculate_xor(self, data: bytes) -> int:
        """
        Calculate XOR checksum

        Args:
            data: Data bytes to calculate checksum for

        Returns:
            int: XOR checksum value
        """
        xor = 0
        for byte in data:
            xor ^= byte
        return xor

    def create_packet(self, command: Command, text: bytes = b'') -> bytes:
        """
        Create a communication packet

        Args:
            command: Command type
            text: Command text data

        Returns:
            bytes: Complete packet with STX, command, length, text, and XOR
        """
        length = len(text)
        packet = self.STX + bytes([command.value, length]) + text
        xor = self.calculate_xor(packet)
        return packet + bytes([xor])

    def parse_packet(self, data: bytes) -> Optional[Tuple[Command, bytes]]:
        """
        Parse received packet

        Args:
            data: Raw packet data

        Returns:
            Tuple of (Command, data) or None if invalid
        """
        if len(data) < 5:
            return None

        if data[0:2] != self.STX:
            return None

        command_value = data[2]
        length = data[3]

        if len(data) < 5 + length:
            return None

        text = data[4:4+length]
        xor_received = data[4+length]
        xor_calculated = self.calculate_xor(data[0:4+length])

        if xor_received != xor_calculated:
            if self.verbose:
                print(f"XOR check failed: received {xor_received:02x}, calculated {xor_calculated:02x}")
            return None

        try:
            command = Command(command_value)
            return command, text
        except ValueError:
            if self.verbose:
                print(f"Unknown command: 0x{command_value:02x}")
            # Return None to ignore unknown commands
            return None

    def send_ack(self) -> bool:
        """
        Send ACK packet

        Returns:
            bool: True if sent successfully
        """
        ack_packet = self.create_packet(Command.ACK)
        try:
            self.serial.write(ack_packet)
            # Don't print ACK sends as they happen constantly
            return True
        except Exception as e:
            print(f"Failed to send ACK: {e}")
            return False

    def queue_command(self, command: Command, text: bytes = b'', user_initiated: bool = True):
        """
        Queue a command to be sent on next POLL

        Args:
            command: Command to send
            text: Command data
            user_initiated: Whether this command was initiated by user (affects output)
        """
        with self.lock:
            packet = self.create_packet(command, text)
            self.command_queue.append({
                'packet': packet,
                'command': command,
                'text': text,
                'retries': 0,
                'max_retries': self.MAX_RETRIES,
                'waiting_ack': False,
                'sent_time': None,
                'user_initiated': user_initiated
            })
            if self.verbose:
                print(f"Queued command: {command.name}")

    def get_next_comm_number(self) -> int:
        """Get and increment communication number"""
        current = self.comm_number
        self.comm_number = (self.comm_number % 255) + 1
        return current

    def handle_poll(self):
        """Handle incoming POLL from VMC"""
        with self.lock:
            # Check if we have a command waiting for ACK
            if self.command_queue and self.command_queue[0].get('waiting_ack'):
                cmd_info = self.command_queue[0]
                # Check timeout (1 second)
                if time.time() - cmd_info['sent_time'] > 1.0:
                    cmd_info['retries'] += 1
                    if cmd_info['retries'] >= cmd_info['max_retries']:
                        if cmd_info.get('user_initiated', True):
                            print(f"[ERROR] Command {cmd_info['command'].name} failed after {cmd_info['max_retries']} retries")
                        self.command_queue.pop(0)
                    else:
                        # Retry - mark as not waiting anymore
                        cmd_info['waiting_ack'] = False

            # Send next queued command if available
            if self.command_queue and not self.command_queue[0].get('waiting_ack'):
                cmd_info = self.command_queue[0]
                try:
                    self.serial.write(cmd_info['packet'])
                    cmd_info['waiting_ack'] = True
                    cmd_info['sent_time'] = time.time()
                    # Only show for user commands or retries
                    if cmd_info.get('user_initiated', True) and (self.verbose or cmd_info['retries'] > 0):
                        print(f"[SENT] {cmd_info['command'].name} (attempt {cmd_info['retries'] + 1})")
                except Exception as e:
                    print(f"Failed to send queued command: {e}")
            else:
                # No command to send, return ACK
                self.send_ack()

    def listen_loop(self):
        """Main listening loop (runs in separate thread)"""
        buffer = b''

        while self.running:
            try:
                if self.serial.in_waiting > 0:
                    data = self.serial.read(self.serial.in_waiting)
                    buffer += data

                    # Try to parse packets from buffer
                    while len(buffer) >= 5:
                        # Look for STX
                        stx_index = buffer.find(self.STX)
                        if stx_index == -1:
                            buffer = b''
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
                print(f"Error in listen loop: {e}")
                time.sleep(0.1)

    def handle_received_packet(self, command: Command, text: bytes):
        """
        Handle received packet from VMC

        Args:
            command: Received command
            text: Packet data
        """
        # Don't print POLL messages as they happen every 200ms
        if command != Command.POLL and self.verbose:
            print(f"Received: {command.name}")

        if command == Command.POLL:
            self.handle_poll()

        elif command == Command.ACK:
            # ACK received for our command
            with self.lock:
                if self.command_queue and self.command_queue[0].get('waiting_ack'):
                    cmd_info = self.command_queue.pop(0)
                    if cmd_info.get('user_initiated', True):
                        print(f"[OK] {cmd_info['command'].name} - Success")

        elif command == Command.AISLE_INFO:
            # Only show if user requested sync
            if not self.suppress_unsolicited or self.verbose:
                self.handle_aisle_info(text)
            self.send_ack()

        elif command == Command.DISPENSING_STATUS:
            self.handle_dispensing_status(text)
            self.send_ack()

        elif command == Command.MACHINE_STATUS_RESPONSE:
            # Only show if user requested it
            if not self.suppress_unsolicited or self.verbose:
                self.handle_machine_status(text)
            self.send_ack()

        elif command == Command.AISLE_STATUS_RESPONSE:
            self.handle_aisle_status_response(text)
            self.send_ack()

        elif command == Command.REQUEST_SYNC:
            if self.verbose:
                print("VMC requests synchronization")
            self.send_ack()
            # Send sync request back (automatic, not user-initiated)
            self.request_info_sync(user_initiated=False)

        elif command == Command.POS_DISPLAY:
            if not self.suppress_unsolicited or self.verbose:
                self.handle_pos_display(text)
            self.send_ack()

        else:
            self.send_ack()

    def handle_aisle_info(self, data: bytes):
        """Parse and display aisle information"""
        if len(data) < 11:
            return

        comm_num = data[0]
        aisle_num = struct.unpack('>H', data[1:3])[0]
        price = struct.unpack('>I', data[3:7])[0]
        inventory = data[7]
        capacity = data[8]
        commodity_num = struct.unpack('>H', data[9:11])[0]
        status = data[11] if len(data) > 11 else 0

        status_text = '[PAUSED]' if status == 1 else '[OK]'
        # Only show aisles with inventory or capacity
        if inventory > 0 or capacity > 0:
            print(f"  Aisle {aisle_num:2d}: {status_text} Stock {inventory}/{capacity}")

    def handle_aisle_status_response(self, data: bytes):
        """Parse and display aisle status response"""
        if len(data) < 4:
            return

        comm_num = data[0]
        status_code = data[1]
        aisle_num = struct.unpack('>H', data[2:4])[0]

        status_names = {
            0x01: "[OK] Ready",
            0x02: "[WARNING] Out of stock",
            0x03: "[ERROR] Doesn't exist",
            0x04: "[PAUSED] Paused"
        }

        status_name = status_names.get(status_code, f"Unknown (0x{status_code:02x})")
        print(f"  Aisle {aisle_num}: {status_name}")

    def handle_dispensing_status(self, data: bytes):
        """Parse and display dispensing status"""
        if len(data) < 3:
            return

        comm_num = data[0]
        status_code = data[1]
        aisle_num = struct.unpack('>H', data[2:4])[0]

        status_names = {
            0x01: "[BUSY] Dispensing...",
            0x02: "[OK] Success",
            0x03: "[ERROR] Jammed",
            0x04: "[WARNING] Motor error",
            0x06: "[ERROR] Motor not found"
        }

        try:
            status = DispensingStatus(status_code)
            status_text = status_names.get(status_code, status.name)
            print(f"  Aisle {aisle_num}: {status_text}")
        except ValueError:
            print(f"  Aisle {aisle_num}: Unknown status 0x{status_code:02x}")

    def handle_machine_status(self, data: bytes):
        """Parse and display machine status"""
        if len(data) < 1:
            return
        print(f"[INFO] Machine status received")

    def handle_pos_display(self, data: bytes):
        """Parse and display POS display request"""
        if len(data) < 19:
            return

        comm_num = data[0]
        text = data[1:17].decode('ascii', errors='ignore').strip('\x00')
        row = data[18]
        print(f"[DISPLAY] '{text}' (Row {row})")

    def start(self):
        """Start the controller (begins listening for VMC polls)"""
        if not self.serial or not self.serial.is_open:
            print("Not connected to vending machine")
            return False

        self.running = True
        self.poll_thread = threading.Thread(target=self.listen_loop, daemon=True)
        self.poll_thread.start()

        # Send initial sync request (suppress output)
        time.sleep(0.5)
        if self.verbose:
            print("Syncing with vending machine...")
        self.request_info_sync(user_initiated=False)
        time.sleep(2)  # Wait for sync to complete
        print("Connected and ready\n")

        return True

    def stop(self):
        """Stop the controller"""
        self.running = False
        if self.poll_thread:
            self.poll_thread.join(timeout=2.0)
        print("Controller stopped")

    # High-level command methods

    def request_info_sync(self, user_initiated: bool = True) -> bool:
        """Request information synchronization"""
        comm_num = self.get_next_comm_number()
        text = bytes([comm_num])
        self.queue_command(Command.REQUEST_SYNC, text, user_initiated)
        return True

    def check_aisle(self, aisle_number: int, user_initiated: bool = True) -> bool:
        """
        Check if aisle is working normally

        Args:
            aisle_number: Aisle number to check

        Returns:
            bool: True if command sent successfully
        """
        comm_num = self.get_next_comm_number()
        aisle_bytes = struct.pack('>H', aisle_number)
        text = bytes([comm_num]) + aisle_bytes
        self.queue_command(Command.CHECK_AISLE, text, user_initiated)
        return True

    def select_buy(self, aisle_number: int, user_initiated: bool = True) -> bool:
        """
        Select to buy from aisle

        Args:
            aisle_number: Aisle number to buy from

        Returns:
            bool: True if command sent successfully
        """
        comm_num = self.get_next_comm_number()
        aisle_bytes = struct.pack('>H', aisle_number)
        text = bytes([comm_num]) + aisle_bytes
        self.queue_command(Command.SELECT_BUY, text, user_initiated)
        return True

    def drive_aisle_direct(self, aisle_number: int, use_drop_sensor: bool = True,
                          use_elevator: bool = False, user_initiated: bool = True) -> bool:
        """
        Drive aisle directly (bypass normal flow)

        Args:
            aisle_number: Aisle number to drive
            use_drop_sensor: Enable drop sensor
            use_elevator: Enable elevator

        Returns:
            bool: True if command sent successfully
        """
        comm_num = self.get_next_comm_number()
        sensor = 1 if use_drop_sensor else 0
        elevator = 1 if use_elevator else 0
        aisle_bytes = struct.pack('>H', aisle_number)
        text = bytes([comm_num, sensor, elevator]) + aisle_bytes
        self.queue_command(Command.DRIVE_AISLE_DIRECT, text, user_initiated)
        return True

    def set_aisle_price(self, aisle_number: int, price: int, user_initiated: bool = True) -> bool:
        """
        Set aisle price

        Args:
            aisle_number: Aisle number (0000=all, 1000-1009=trays 0-9)
            price: Price in smallest currency unit

        Returns:
            bool: True if command sent successfully
        """
        comm_num = self.get_next_comm_number()
        aisle_bytes = struct.pack('>H', aisle_number)
        price_bytes = struct.pack('>I', price)
        text = bytes([comm_num]) + aisle_bytes + price_bytes
        self.queue_command(Command.SET_AISLE_PRICE, text, user_initiated)
        return True

    def set_aisle_inventory(self, aisle_number: int, inventory: int, user_initiated: bool = True) -> bool:
        """
        Set aisle inventory

        Args:
            aisle_number: Aisle number
            inventory: Inventory count

        Returns:
            bool: True if command sent successfully
        """
        comm_num = self.get_next_comm_number()
        aisle_bytes = struct.pack('>H', aisle_number)
        text = bytes([comm_num]) + aisle_bytes + bytes([inventory])
        self.queue_command(Command.SET_AISLE_INVENTORY, text, user_initiated)
        return True

    def set_aisle_capacity(self, aisle_number: int, capacity: int, user_initiated: bool = True) -> bool:
        """
        Set aisle capacity

        Args:
            aisle_number: Aisle number
            capacity: Maximum capacity

        Returns:
            bool: True if command sent successfully
        """
        comm_num = self.get_next_comm_number()
        aisle_bytes = struct.pack('>H', aisle_number)
        text = bytes([comm_num]) + aisle_bytes + bytes([capacity])
        self.queue_command(Command.SET_AISLE_CAPACITY, text, user_initiated)
        return True

    def request_machine_status(self, user_initiated: bool = True) -> bool:
        """Request machine status"""
        comm_num = self.get_next_comm_number()
        text = bytes([comm_num])
        self.queue_command(Command.REQUEST_MACHINE_STATUS, text, user_initiated)
        return True

    def cancel_selection(self, user_initiated: bool = True) -> bool:
        """Cancel current aisle selection"""
        comm_num = self.get_next_comm_number()
        aisle_bytes = struct.pack('>H', 0x0000)
        text = bytes([comm_num]) + aisle_bytes
        self.queue_command(Command.SELECT_AISLE, text, user_initiated)


def main():
    """Example usage and testing"""
    print("=" * 60)
    print("Vending Machine Controller")
    print("=" * 60)

    # Configure your serial port here
    port = input("\nSerial port (e.g., COM3): ").strip()

    if not port:
        port = "COM3"  # Default for Windows
        print(f"Using default: {port}")

    controller = VendingMachineController(port, verbose=False)

    if not controller.connect():
        print("[ERROR] Connection failed. Check your serial port.")
        return

    try:
        controller.start()

        print("=" * 60)
        print("Available commands:")
        print("  1 - Check aisle status")
        print("  2 - Select and buy")
        print("  3 - Drive aisle directly")
        print("  4 - Set aisle price")
        print("  5 - Request machine status")
        print("  6 - Request info sync")
        print("  q - Quit")
        print("=" * 60)

        while True:
            try:
                cmd = input("\n> ").strip().lower()
            except EOFError:
                break

            if cmd == 'q' or cmd == 'quit':
                break

            elif cmd == '1':
                aisle = int(input("  Aisle number: "))
                print(f"Checking aisle {aisle}...")
                controller.check_aisle(aisle)

            elif cmd == '2':
                aisle = int(input("  Aisle number: "))
                print(f"Buying from aisle {aisle}...")
                controller.select_buy(aisle)

            elif cmd == '3':
                aisle = int(input("  Aisle number: "))
                print(f"Driving aisle {aisle}...")
                controller.drive_aisle_direct(aisle)

            elif cmd == '4':
                aisle = int(input("  Aisle number (0=all): "))
                price = int(input("  Price (cents): "))
                print(f"Setting price...")
                controller.set_aisle_price(aisle, price)

            elif cmd == '5':
                print("Requesting status...")
                controller.request_machine_status()

            elif cmd == '6':
                print("Requesting sync...")
                controller.request_info_sync()

            elif cmd:
                print("[ERROR] Unknown command")

            time.sleep(0.3)

    except KeyboardInterrupt:
        print("\n\nStopped by user")

    finally:
        controller.disconnect()
        print("Goodbye!")


if __name__ == "__main__":
    main()
