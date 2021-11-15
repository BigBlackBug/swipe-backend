import os
import sys

# TODO WTF
sys.path.insert(1, os.path.join(sys.path[0], '..'))

import uvicorn
import firebase_admin
from firebase_admin import credentials
from swipe.settings import settings

if __name__ == '__main__':
    cred = credentials.Certificate(settings.GOOGLE_APPLICATION_CREDENTIALS)
    firebase_admin.initialize_app(cred)
    uvicorn.run('swipe.chat_server.server:app', host='0.0.0.0',  # noqa
                port=settings.CHAT_SERVER_PORT, workers=1)
