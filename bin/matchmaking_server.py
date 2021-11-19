import os
import sys

# TODO WTF
import sentry_sdk

sys.path.insert(1, os.path.join(sys.path[0], '..'))
from swipe import config

config.configure_logging()
from swipe.settings import settings
from swipe.matchmaking import mm_websocket_server as matchmaking_server

if settings.SENTRY_MATCHMAKING_SERVER_URL:
    sentry_sdk.init(
        settings.SENTRY_MATCHMAKING_SERVER_URL,
        # TODO change in prod
        traces_sample_rate=settings.SENTRY_SAMPLE_RATE
    )

if __name__ == '__main__':
    matchmaking_server.start_server()
