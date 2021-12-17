import logging
from typing import Optional

import requests

from swipe.settings import settings

logger = logging.getLogger(__name__)

BASE_URL = f'{settings.CHAT_SERVER_HOST}/events/'


def send_blacklist_event(blocked_by_id: str, blocked_user_id: str):
    logger.info(f"Calling chat server to send blacklisted event: "
                f"{blocked_by_id} blocked {blocked_user_id}")
    # sending 'add to blacklist' event to blocked_user_id
    requests.post(BASE_URL + 'blacklist', json={
        'blocked_by_id': blocked_by_id,
        'blocked_user_id': blocked_user_id
    })


def send_user_deleted_event(user_id: str,
                            recipients: Optional[list[str]] = None):
    if recipients:
        # we gotta notify every chat participant that the user is gone
        requests.post(BASE_URL + 'user_deleted', json={
            'user_id': str(user_id),
            'recipients': recipients
        })
    else:
        requests.post(BASE_URL + 'user_deleted', json={
            'user_id': str(user_id),
        })


def send_rating_changed_event(target_user_id: str, rating: int,
                              sender_id: Optional[str] = None):
    logger.info(f"Calling chat server to send rating_changed event to "
                f"user_id: {target_user_id}")
    if not sender_id:
        sender_id = target_user_id

    requests.post(BASE_URL + 'rating_changed', json={
        'user_id': target_user_id,
        'sender_id': sender_id,
        'rating': rating
    })
