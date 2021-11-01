import logging
import random
import secrets

import requests

from settings import settings

logger = logging.getLogger(__name__)


def fetch_online_users(room_id: str):
    # TODO there has to be a better way than this
    # fetching a random handle out of all connections is stupid
    resp = requests.post(settings.JANUS_GATEWAY_ADMIN_URL, json={
        'janus': 'list_sessions',
        'transaction': secrets.token_urlsafe(16)
    })
    sessions = resp.json()['sessions']
    if not sessions:
        logger.info("No active users detected")
        return []

    session = random.choice(sessions)

    resp = requests.post(settings.JANUS_GATEWAY_ADMIN_URL, json={
        'janus': 'list_handles',
        'session_id': session,
        'transaction': secrets.token_urlsafe(16)
    })
    handle = random.choice(resp.json()['handles'])
    resp = requests.post(
        f'{settings.JANUS_GATEWAY_URL}/{session}/{handle}',
        json={
            'body': {
                'request': 'listparticipants',
                'room': room_id
            },
            'janus': 'message',
            'transaction': secrets.token_urlsafe(16)
        })
    response_data = resp.json()
    participants = response_data['plugindata']['data']['participants']
    logger.info(f"Got {len(participants)} participants:\n{participants} "
                f"in room {room_id}")

    return participants
