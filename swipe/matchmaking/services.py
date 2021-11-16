import datetime
import logging
from typing import Optional
from uuid import UUID

from dateutil.relativedelta import relativedelta
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

import swipe.swipe_server.misc.dependencies as dependencies
from swipe.swipe_server.users.enums import Gender
from swipe.swipe_server.users.models import IDList, User

logger = logging.getLogger(__name__)


class MMUserService:
    def __init__(self, db: Session = Depends(dependencies.db)):
        self.db = db

    def find_user_ids(self,
                      current_user_id: str,
                      age: int,
                      age_difference,
                      online_users: set[str],
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
        return self.db.execute(select(User.id, User.date_of_birth).
                               where(User.id == user_id)).one_or_none()
