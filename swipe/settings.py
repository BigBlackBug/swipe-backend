import os
from pathlib import Path
from typing import Optional

from pydantic import BaseSettings, PostgresDsn, RedisDsn


class Constants(BaseSettings):
    SWIPES_PER_TIME_PERIOD = 50
    # TODO make it 30 mins
    SWIPES_REAP_TIMEOUT_SEC = 2 * 60
    SWIPES_DEFAULT_NUMBER = 30

    CALL_FEEDBACK_RATING_DIFF = 5

    RATING_UPDATE_AD_WATCHED = 100
    RATING_UPDATE_FRIEND_REFERRED = 100
    RATING_UPDATE_APP_REVIEWED = 100
    RATING_UPDATE_PREMIUM_ACTIVATED = 100

    RECENTLY_ONLINE_TTL_SEC = 60 * 60
    POPULAR_CACHE_POPULATE_JOB_TIMEOUT_SEC = 60 * 60
    RECENTLY_ONLINE_CLEAR_JOB_TIMEOUT_SEC = 10 * 60

    BASE_DIR: Path = Path('.')


class Settings(BaseSettings):
    API_V1_PREFIX: str = "/v1"
    SWIPE_SECRET_KEY: str

    SWIPE_PORT: Optional[int] = None
    DATABASE_URL: Optional[PostgresDsn] = None
    REDIS_URL: Optional[RedisDsn] = None

    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = None

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
    MATCHMAKING_TEXT_CHAT_SERVER_PORT: Optional[int]

    MATCHMAKING_ROUND_LENGTH_SECS = 5
    MATCHMAKING_DEFAULT_AGE_DIFF = 20
    MATCHMAKING_MAX_AGE_DIFF = 20
    MATCHMAKING_AGE_DIFF_STEP = 5

    ONLINE_USER_MAX_AGE_DIFF = 10
    ONLINE_USER_DEFAULT_AGE_DIFF = 2
    ONLINE_USER_AGE_DIFF_STEP = 2
    ONLINE_USER_RESPONSE_CACHE_TTL = 60 * 60

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
