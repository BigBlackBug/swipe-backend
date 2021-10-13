from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from swipe import dependencies
from swipe.users import schemas, models


class UserService:
    def __init__(self, db: Session = Depends(dependencies.db)):
        self.db = db

    def create_user(self, user_name: str) -> models.User:
        user_object = models.User(name=user_name)
        self.db.add(user_object)
        self.db.commit()
        self.db.refresh(user_object)
        return user_object

    def get_user(self, user_id: UUID) -> models.User:
        return self.db.execute(
            select(models.User).where(models.User.id == user_id)) \
            .scalar_one_or_none()

    def get_users(self) -> list[models.User]:
        return self.db.execute(select(models.User)).scalars().all()

    def update_user(self, user_object: models.User, user: schemas.UserIn):
        # TODO think of a way to update photos EZ
        for k, v in user.dict(exclude_unset=True).items():
            setattr(user_object, k, v)
        self.db.commit()
        self.db.refresh(user_object)
        return user_object

    def add_photo(self, user_object: models.User, photo_name: str):
        user_object.photos = user_object.photos + [photo_name]
        self.db.commit()
