import os
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseSettings, PostgresDsn, validator


class Constants(BaseSettings):
    FREE_SWIPES_PER_TIME_PERIOD = 50
    # TODO change in production
    # FREE_SWIPES_COOLDOWN_SEC = 30 * 60
    FREE_SWIPES_COOLDOWN_SEC = 10

    ONLINE_USER_COOLDOWN_SEC = 60
    FREE_SWIPES_REDIS_PREFIX = 'free_swipes_cooldown_'
    ONLINE_USER_PREFIX = 'online_global_'
    ONLINE_USER_LOBBY_PREFIX = 'online_lobby_'

    BASE_DIR: Path = Path('.')


class Settings(BaseSettings):
    API_V1_PREFIX: str = "/v1"
    SWIPE_SECRET_KEY: str

    PORT: Optional[int] = None
    DATABASE_URL: Optional[PostgresDsn] = None

    STORAGE_ACCESS_KEY: str
    STORAGE_SECRET_KEY: str
    STORAGE_ENDPOINT: str = 'https://storage.yandexcloud.net'
    STORAGE_REGION: str = 'ru-central1'

    # TODO debug mode
    ENABLE_SQL_ECHO: Optional[bool] = True
    ENABLE_WEB_SERVER_AUTORELOAD: Optional[bool] = False
    ENABLE_ONLINE_CACHE_JOB: Optional[bool] = True

    REDIS_URL: str
    JANUS_GATEWAY_URL: str = None
    JANUS_GATEWAY_ADMIN_URL: str = None
    JANUS_GATEWAY_GLOBAL_ROOM_ID: str = 'global'
    JANUS_GATEWAY_LOBBY_ROOM_ID: str = 'lobby'

    @validator("DATABASE_URL")
    def fix_database_uri_for_heroku(
            cls, value: Optional[str], values: Dict[str, Any]) -> Any:
        # https://github.com/sqlalchemy/sqlalchemy/issues/6083#issuecomment-801478013
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql://", 1)
        return value

    class Config:
        case_sensitive = True
        env_file = os.environ.get('SWIPE_ENV_FILE', '.env')


settings = Settings()
constants = Constants()
