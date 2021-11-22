import datetime
import logging
from typing import Optional, Iterable
from uuid import UUID

from dateutil.relativedelta import relativedelta
from fastapi import Depends
from sqlalchemy import select, insert
from sqlalchemy.orm import Session, load_only

import swipe.swipe_server.misc.dependencies as dependencies
from swipe.settings import settings
from swipe.swipe_server.users.enums import Gender
from swipe.swipe_server.users.models import IDList, User, blacklist_table

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
                      ) -> IDList:
        gender_clause = True if not gender else User.gender == gender
        min_age = datetime.datetime.utcnow() - relativedelta(
            years=age + age_difference)
        max_age = datetime.datetime.utcnow() + relativedelta(
            years=age + age_difference)

        query = select(User.id). \
            where(gender_clause). \
            where(User.date_of_birth.between(min_age, max_age)). \
            where(User.id != current_user_id). \
            where(User.id.in_(online_users)). \
            where(~User.blocked_by.any(id=current_user_id))
        return self.db.execute(query).scalars().all()

    def get_matchmaking_preview(self, user_id: UUID):
        return self.db.query(User).where(User.id == user_id). \
            options(load_only(User.date_of_birth, User.gender)).one_or_none()

    def update_blacklist(self, blocker_id: str, blocked_user_id: str):
        if settings.ENABLE_MATCHMAKING_BLACKLIST:
            self.db.execute(insert(blacklist_table).values(
                blocked_user_id=blocked_user_id,
                blocked_by_id=blocker_id))
            self.db.commit()
