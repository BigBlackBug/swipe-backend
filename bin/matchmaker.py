import os
import sys

# TODO WTF
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
from swipe.matchmaking import matchmaker

if __name__ == '__main__':
    asyncio.run(matchmaker.run_server())
