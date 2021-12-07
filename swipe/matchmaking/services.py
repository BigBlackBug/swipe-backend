import logging

from fastapi import Depends
from sqlalchemy import select, cast, String, union_all
from sqlalchemy.orm import Session, load_only

import swipe.swipe_server.misc.dependencies as dependencies
from swipe.swipe_server.chats.models import Chat
from swipe.swipe_server.users.models import User

logger = logging.getLogger(__name__)


class MMUserService:
    def __init__(self, db: Session = Depends(dependencies.db)):
        self.db = db

    def get_matchmaking_preview(self, user_id: str) -> User:
        logger.info(f"Fetching chat matchmaking preview of {user_id}")
        return self.db.query(User).where(User.id == user_id). \
            options(load_only(User.gender, User.date_of_birth)) \
            .one_or_none()

    def get_user_chat_partners(self, user_id: str) -> list[str]:
        logger.info(f"Fetching chat partners of {user_id}")
        a_to_b = select(cast(Chat.the_other_person_id, String)).where(
            Chat.initiator_id == user_id
        )
        b_to_a = select(cast(Chat.initiator_id, String)).where(
            Chat.the_other_person_id == user_id
        )
        return self.db.execute(union_all(a_to_b, b_to_a)).scalars().all()
