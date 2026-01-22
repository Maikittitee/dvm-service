# DVM Service (Dispense Vending Machine Service)

API service for controlling automated medicine dispensing machines via RS232 protocol.

## Prerequisites

- Python 3.8 or higher
- RS232 serial port (e.g., `/dev/ttyUSB0` on Linux)
- VMC (Vending Machine Controller) supporting JSK protocol

## Installation

### 1. Clone repository
```bash
git clone <repository-url>
cd dvm-service
```

### 2. Create virtual environment
```bash
python3 -m venv env
```

### 3. Activate virtual environment
```bash
source env/bin/activate
```

### 4. Install dependencies
```bash
pip3 install -r requirements.txt
```

## Quick Start

### Run development server
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Test API
Open browser at: `http://localhost:8000/docs`

## API Endpoints