import secrets
from typing import Any, Dict, Optional

from pydantic import BaseSettings, PostgresDsn, validator


class Settings(BaseSettings):
    API_V1_PREFIX: str = "/v1"
    SECRET_KEY: str = secrets.token_urlsafe(32)

    # TODO debug mode
    ENABLE_SQL_ECHO: Optional[bool] = True
    DATABASE_URI: Optional[PostgresDsn] = None

    # POSTGRES_SERVER: Optional[str] = None
    # POSTGRES_USER: Optional[str] = None
    # POSTGRES_PASSWORD: Optional[str] = None
    # POSTGRES_DB: Optional[str] = None
    #

    #
    # @validator("DATABASE_URI", pre=True)
    # def assemble_db_connection(cls, v: Optional[str],
    #                            values: Dict[str, Any]) -> Any:
    #     if isinstance(v, str):
    #         return v
    #     return PostgresDsn.build(
    #         scheme="postgresql",
    #         user=values.get("POSTGRES_USER"),
    #         password=values.get("POSTGRES_PASSWORD"),
    #         host=values.get("POSTGRES_SERVER"),
    #         path=f"/{values.get('POSTGRES_DB') or ''}",
    #     )

    class Config:
        case_sensitive = True
        env_file = '.env'
        env_prefix = 'SWIPE_'


settings = Settings()
