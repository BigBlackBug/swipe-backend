import os
import sys

# TODO WTF
import time

sys.path.insert(1, os.path.join(sys.path[0], '..'))
from swipe import config

config.configure_logging()
import sentry_sdk
import asyncio
from swipe.settings import settings

if settings.SENTRY_MATCHMAKER_URL:
    sentry_sdk.init(
        settings.SENTRY_MATCHMAKER_URL,
        # TODO change in prod
        traces_sample_rate=settings.SENTRY_SAMPLE_RATE
    )
from swipe.matchmaking import mm_main_server

if __name__ == '__main__':
    time.sleep(1)
    asyncio.run(mm_main_server.run_server())
