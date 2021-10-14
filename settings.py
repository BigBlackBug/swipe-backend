from typing import Any, Dict, Optional

from pydantic import BaseSettings, PostgresDsn, validator


class Settings(BaseSettings):
    API_V1_PREFIX: str = "/v1"
    # SECRET_KEY: str = secrets.token_urlsafe(32)
    SECRET_KEY: str = 'oEA5LF15Kh84fS3KmQWxB3PXkmJrkwRZ88zAkGC2v4c'
    # set by heroku
    PORT: Optional[int] = None
    DATABASE_URL: Optional[PostgresDsn] = None

    STORAGE_ACCESS_KEY: str
    STORAGE_SECRET_KEY: str
    # TODO debug mode
    ENABLE_SQL_ECHO: Optional[bool] = True
    ENABLE_WEB_SERVER_AUTORELOAD: Optional[bool] = False

    @validator("DATABASE_URL")
    def fix_database_uri_for_heroku(cls, value: Optional[str],
                                    values: Dict[str, Any]) -> Any:
        # https://github.com/sqlalchemy/sqlalchemy/issues/6083#issuecomment-801478013
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql://", 1)
        return value

    # POSTGRES_SERVER: Optional[str] = None
    # POSTGRES_USER: Optional[str] = None
    # POSTGRES_PASSWORD: Optional[str] = None
    # POSTGRES_DB: Optional[str] = None
    #

    #
    # @validator("DATABASE_URL", pre=True)
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


settings = Settings()
