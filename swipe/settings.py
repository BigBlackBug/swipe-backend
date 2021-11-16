import os
from pathlib import Path
from typing import Optional

from pydantic import BaseSettings, PostgresDsn


class Constants(BaseSettings):
    FREE_SWIPES_PER_TIME_PERIOD = 50
    # TODO change in production
    # FREE_SWIPES_COOLDOWN_SEC = 30 * 60
    FREE_SWIPES_COOLDOWN_SEC = 10

    FREE_SWIPES_REDIS_PREFIX = 'free_swipes_cooldown_'

    BASE_DIR: Path = Path('.')


class Settings(BaseSettings):
    API_V1_PREFIX: str = "/v1"
    SWIPE_SECRET_KEY: str

    SWIPE_PORT: Optional[int] = None
    DATABASE_URL: Optional[PostgresDsn] = None

    STORAGE_ACCESS_KEY: str
    STORAGE_SECRET_KEY: str
    STORAGE_ENDPOINT: str = 'https://storage.yandexcloud.net'
    STORAGE_REGION: str = 'ru-central1'

    # TODO debug mode
    ENABLE_SQL_ECHO: Optional[bool] = True
    ENABLE_WEB_SERVER_AUTORELOAD: Optional[bool] = False

    MATCHMAKER_HOST: Optional[str]
    MATCHMAKER_PORT: Optional[int]
    CHAT_SERVER_PORT: Optional[int]
    MATCHMAKING_SERVER_PORT: Optional[int]

    REDIS_URL: str

    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = None

    class Config:
        case_sensitive = True
        env_file = os.environ.get('SWIPE_ENV_FILE', '.env')


settings = Settings()
constants = Constants()
