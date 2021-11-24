import os
import sys

sys.path.insert(1, os.path.join(sys.path[0], '..'))
from swipe import config

config.configure_logging()
import sentry_sdk
from swipe.settings import settings

if settings.SENTRY_MATCHMAKER_URL:
    sentry_sdk.init(
        settings.SENTRY_MATCHMAKER_URL,
        # TODO change in prod
        traces_sample_rate=settings.SENTRY_SAMPLE_RATE
    )
from swipe.matchmaking import matchmaker

if __name__ == '__main__':
    # Yeah, that's a stupid workaround
    # But we need the matchmaker server to start first
    matchmaker.start_matchmaker(
        round_length_secs=settings.MATCHMAKING_ROUND_LENGTH_SECS)
