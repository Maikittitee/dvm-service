# DVM Service (Drug Vending Machine Service)

API service for controlling automated drug/medicine dispensing machines via RS232 protocol.

## Features

- RESTful API for vending machine control
- Dispense products from specified aisles/trays
- Check aisle status (stock, availability)
- Health and readiness endpoints
- Docker support with multi-stage builds
- Clean architecture with separation of concerns

## Prerequisites

- Python 3.12+
- RS232 serial port (e.g., `/dev/ttyUSB0` on Linux, `COM3` on Windows)
- VMC (Vending Machine Controller) supporting JSK protocol

## Project Structure

```
dvm-service/
├── app/
│   ├── api/
│   │   ├── v1/
│   │   │   ├── endpoints/
│   │   │   │   ├── dispense.py    # Dispense endpoints
│   │   │   │   └── health.py      # Health check endpoints
│   │   │   └── router.py          # API router
│   │   └── deps.py                # Dependencies
│   ├── core/
│   │   └── vmc_controller.py      # VMC communication
│   ├── schemas/
│   │   └── dispense.py            # Pydantic models
│   ├── services/
│   │   └── dispense_service.py    # Business logic
│   ├── config.py                  # Configuration
│   └── main.py                    # Application entry
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## Installation

### Local Development

```bash
# Clone repository
git clone <repository-url>
cd dvm-service

# Create virtual environment
python3 -m venv env
source env/bin/activate  # Linux/macOS
# or: env\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp .env.example .env
# Edit .env with your serial port configuration

# Run development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Configuration

Environment variables (set in `.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_NAME` | DVM Service | Application name |
| `DEBUG` | false | Debug mode |
| `SERIAL_PORT` | /dev/ttyUSB0 | Serial port for VMC |
| `SERIAL_BAUDRATE` | 57600 | Serial baud rate |
| `API_PORT` | 8000 | API server port |

## API Endpoints

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/health` | Health check with VMC status |
| GET | `/api/v1/ready` | Readiness check |

### Dispense

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/dispense` | Dispense with full options |
| POST | `/api/v1/aisle/{aisle_number}/dispense` | Simple dispense from aisle |
| GET | `/api/v1/aisle/{aisle_number}/status` | Check aisle status |

### API Documentation

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

## Usage Examples

### Dispense from aisle

```bash
# Simple dispense
curl -X POST http://localhost:8000/api/v1/aisle/1/dispense

# Dispense with options
curl -X POST http://localhost:8000/api/v1/dispense \
  -H "Content-Type: application/json" \
  -d '{
    "aisle_number": 1,
    "use_drop_sensor": true,
    "use_elevator": false,
    "direct_drive": false
  }'
```

### Check aisle status

```bash
curl http://localhost:8000/api/v1/aisle/1/status
```

### Health check

```bash
curl http://localhost:8000/api/v1/health
```

## Response Examples

### Successful dispense

```json
{
  "success": true,
  "aisle_number": 1,
  "status": "success",
  "message": "Product dispensed successfully",
  "transaction_id": "txn_abc123def456"
}
```

### Aisle status

```json
{
  "aisle_number": 1,
  "status": "normal",
  "message": "Aisle is ready"
}
```

## Serial Port Setup

### macOS

```bash
# List available serial ports
ls /dev/cu.*

# Your USB serial adapter will appear as:
# /dev/cu.usbserial-XXXXX (e.g., /dev/cu.usbserial-DN45JVV4)

# Set in .env or export
export SERIAL_PORT=/dev/cu.usbserial-DN45JVV4

# Run locally (Docker cannot access serial on macOS)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Linux

```bash
# Add user to dialout group for serial access
sudo usermod -a -G dialout $USER

# Check serial port
ls -la /dev/ttyUSB*

# Test connection
screen /dev/ttyUSB0 57600

# Run with Docker
SERIAL_PORT=/dev/ttyUSB0 docker compose --profile linux up -d
```
