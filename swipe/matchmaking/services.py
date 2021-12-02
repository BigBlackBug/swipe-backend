import datetime
import logging
from typing import Optional, Iterable

from dateutil.relativedelta import relativedelta
from fastapi import Depends
from sqlalchemy import select, cast, String, union_all
from sqlalchemy.orm import Session, load_only

import swipe.swipe_server.misc.dependencies as dependencies
from swipe.swipe_server.chats.models import Chat
from swipe.swipe_server.users.enums import Gender
from swipe.swipe_server.users.models import User

logger = logging.getLogger(__name__)


class MMUserService:
    def __init__(self, db: Session = Depends(dependencies.db)):
        self.db = db

    def find_user_ids(self,
                      current_user_id: str,
                      age: int,
                      age_difference,
                      online_users: Iterable[str],
                      gender: Optional[Gender] = None,
                      ) -> list[str]:
        gender_clause = True if not gender else User.gender == gender
        min_age = datetime.datetime.utcnow() - relativedelta(
            years=age + age_difference)
        max_age = datetime.datetime.utcnow() + relativedelta(
            years=age + age_difference)

        a_to_b = select(Chat.the_other_person_id).where(
            Chat.initiator_id == current_user_id
        )
        b_to_a = select(Chat.initiator_id).where(
            Chat.the_other_person_id == current_user_id
        )
        users_with_chat = self.db.execute(
            union_all(a_to_b, b_to_a)).scalars().all()
        query = select(cast(User.id, String)). \
            where(gender_clause). \
            where(User.date_of_birth.between(min_age, max_age)). \
            where(User.id != current_user_id). \
            where(User.id.not_in(users_with_chat)). \
            where(User.id.in_(online_users)). \
            where(~User.blocked_by.any(id=current_user_id))

        return self.db.execute(query).scalars().all()

    def get_matchmaking_preview(self, user_id: str):
        return self.db.query(User).where(User.id == user_id). \
            options(load_only(User.gender, User.date_of_birth)) \
            .one_or_none()
