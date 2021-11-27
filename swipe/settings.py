import os
from pathlib import Path
from typing import Optional

from pydantic import BaseSettings, PostgresDsn


class Constants(BaseSettings):
    FREE_SWIPES_PER_TIME_PERIOD = 50
    # TODO make it 30 mins
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
    ENABLE_MATCHMAKING_BLACKLIST: Optional[bool] = False
    ENABLE_BLACKLIST: Optional[bool] = False

    CHAT_SERVER_PORT: Optional[int]
    CHAT_SERVER_HOST: Optional[str]
    MATCHMAKING_SERVER_HOST: Optional[str]
    MATCHMAKING_SERVER_PORT: Optional[int]

    MATCHMAKING_ROUND_LENGTH_SECS = 5
    MATCHMAKING_DEFAULT_AGE_DIFF = 20
    MATCHMAKING_MAX_AGE_DIFF = 20
    MATCHMAKING_AGE_DIFF_STEP = 5

    ONLINE_USER_MAX_AGE_DIFF = 20
    ONLINE_USER_DEFAULT_AGE_DIFF = 10
    ONLINE_USER_AGE_DIFF_STEP = 5
    ONLINE_USER_RESPONSE_CACHE_TTL = 60 * 60

    # TODO make it 10 mins
    USER_CACHE_TTL_SECS = 60

    REDIS_URL: str

    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = None

    SENTRY_SWIPE_SERVER_URL: Optional[str] = None
    SENTRY_MATCHMAKER_URL: Optional[str] = None
    SENTRY_MATCHMAKING_SERVER_URL: Optional[str] = None
    SENTRY_CHAT_SERVER_URL: Optional[str] = None

    SENTRY_SAMPLE_RATE = 1.0

    class Config:
        case_sensitive = True
        env_file = os.environ.get('SWIPE_ENV_FILE', '.env')


settings = Settings()
constants = Constants()
