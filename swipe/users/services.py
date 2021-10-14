from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

import swipe.database
from swipe.users import schemas, models
from swipe.users.models import AuthInfo


class UserService:
    def __init__(self, db: Session = Depends(swipe.database.db)):
        self.db = db

    def create_user(self,
                    user_payload: schemas.CreateUserIn) -> models.User:
        auth_info = AuthInfo(
            auth_provider=user_payload.auth_provider,
            payload={'provider_token': user_payload.provider_token})
        user_object = models.User()
        user_object.auth_info = auth_info

        self.db.add(auth_info)
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

    def delete_photo(self, user_object: models.User, photo_index: int):
        new_list = list(user_object.photos)
        new_list.pop(photo_index)
        user_object.photos = new_list
        self.db.commit()
