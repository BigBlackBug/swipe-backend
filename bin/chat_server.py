import os
import sys

sys.path.insert(1, os.path.join(sys.path[0], '..'))
from swipe import config

config.configure_logging()
import firebase_admin
from firebase_admin import credentials
from swipe.settings import settings
from swipe.chat_server import server

if settings.SENTRY_CHAT_SERVER_URL:
    import sentry_sdk

    sentry_sdk.init(
        settings.SENTRY_CHAT_SERVER_URL,
        traces_sample_rate=settings.SENTRY_SAMPLE_RATE,
        release=settings.SWIPE_VERSION
    )
if __name__ == '__main__':
    cred = credentials.Certificate(settings.GOOGLE_APPLICATION_CREDENTIALS)
    firebase_admin.initialize_app(cred)
    server.start_server()
