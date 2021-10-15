from typing import Any, Dict, Optional

from pydantic import BaseSettings, PostgresDsn, validator


class Settings(BaseSettings):
    API_V1_PREFIX: str = "/v1"
    SWIPE_SECRET_KEY: str

    PORT: Optional[int] = None
    DATABASE_URL: Optional[PostgresDsn] = None

    STORAGE_ACCESS_KEY: str
    STORAGE_SECRET_KEY: str

    # TODO debug mode
    ENABLE_SQL_ECHO: Optional[bool] = True
    ENABLE_WEB_SERVER_AUTORELOAD: Optional[bool] = False

    class Config:
        case_sensitive = True


settings = Settings()
