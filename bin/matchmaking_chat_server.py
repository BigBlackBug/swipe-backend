import os
import sys

import sentry_sdk

sys.path.insert(1, os.path.join(sys.path[0], '..'))
from swipe import config

config.configure_logging()
from swipe.settings import settings
from swipe.mm_chat_server import server as chat_server

if settings.SENTRY_CHAT_SERVER_URL:
    sentry_sdk.init(
        settings.SENTRY_CHAT_SERVER_URL,
        # TODO change in prod
        traces_sample_rate=settings.SENTRY_SAMPLE_RATE
    )

if __name__ == '__main__':
    chat_server.start_server()
