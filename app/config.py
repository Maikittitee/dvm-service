from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    app_name: str = "DVM Service"
    app_version: str = "1.0.0"
    debug: bool = False

    serial_port: str = "/dev/ttyUSB0"
    serial_baudrate: int = 57600
    serial_timeout: float = 0.1

    vmc_poll_interval: float = 0.2
    vmc_command_timeout: float = 1.0
    vmc_max_retries: int = 5

    api_prefix: str = "/api/v1"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
