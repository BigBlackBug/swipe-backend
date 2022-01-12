import logging
import os
import sys

import sentry_sdk

sys.path.insert(1, os.path.join(sys.path[0], '..'))

from swipe import config

config.configure_logging()
import asyncio
import time

import schedule

from swipe.swipe_server.users import swipe_bg_tasks
from swipe.settings import constants, settings

if settings.SENTRY_SWIPE_SERVER_URL:
    sentry_sdk.init(
        settings.SENTRY_SWIPE_SERVER_URL,
        traces_sample_rate=settings.SENTRY_SAMPLE_RATE,
        release=settings.SWIPE_VERSION
    )
logger = logging.getLogger(__name__)
loop = asyncio.get_event_loop()


def populate_popular_cache():
    loop.run_until_complete(swipe_bg_tasks.populate_popular_cache())


def update_recently_online_cache():
    loop.run_until_complete(swipe_bg_tasks.update_recently_online_cache())


if __name__ == '__main__':
    logger.info("Starting the cache updater")
    schedule.every(constants.POPULAR_CACHE_POPULATE_JOB_TIMEOUT_SEC). \
        seconds.do(populate_popular_cache)
    schedule.every(constants.RECENTLY_ONLINE_CLEAR_JOB_TIMEOUT_SEC). \
        seconds.do(update_recently_online_cache)

    while True:
        schedule.run_pending()
        time.sleep(1)
