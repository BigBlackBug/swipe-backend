import logging

import aioredis
import requests
from fastapi import Depends
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from swipe.settings import settings
from swipe.swipe_server import events
from swipe.swipe_server.misc import dependencies
from swipe.swipe_server.misc.errors import SwipeError
from swipe.swipe_server.users.models import blacklist_table
from swipe.swipe_server.users.services.redis_services import \
    RedisBlacklistService
from swipe.swipe_server.utils import enable_blacklist

logger = logging.getLogger(__name__)


class BlacklistService:
    def __init__(self, db: Session = Depends(dependencies.db),
                 redis: aioredis.Redis = Depends(dependencies.redis)):
        self.db = db
        self.redis_blacklist = RedisBlacklistService(redis)

    @enable_blacklist()
    async def update_blacklist(
            self, blocked_by_id: str, blocked_user_id: str,
            send_blacklist_event: bool = False):
        logger.info(f"{blocked_by_id} blocked {blocked_user_id}, updating db")
        try:
            self.db.execute(insert(blacklist_table).values(
                blocked_user_id=blocked_user_id,
                blocked_by_id=blocked_by_id))
            self.db.commit()
        except IntegrityError:
            raise SwipeError(f"{blocked_user_id} is "
                             f"already blocked by {blocked_by_id}")

        await self.redis_blacklist.add_to_blacklist_cache(
            blocked_by_id, blocked_user_id)

        if send_blacklist_event:
            events.send_blacklist_event(blocked_by_id, blocked_user_id)
