import time
import uuid
from typing import Optional
from uuid import UUID

from aioredis import Redis
from fastapi import Depends, UploadFile
from jose import jwt
from jose.constants import ALGORITHMS
from sqlalchemy import select
from sqlalchemy.orm import Session

import swipe.dependencies
from settings import settings, constants
from swipe.storage import CloudStorage
from swipe.users import schemas, models


class RedisService:
    def __init__(self,
                 redis: Redis = Depends(swipe.dependencies.redis)):
        self.redis = redis

    async def reset_swipe_reap_timestamp(
            self, user_object: models.User) -> int:
        """
        Sets the timestamp for when the free swipes can be reaped
        for the specified user

        :param user_object:
        :return: new timestamp
        """
        reap_timestamp = int(time.time() + constants.FREE_SWIPES_COOLDOWN_SEC)
        await self.redis.setex(
            f'{constants.FREE_SWIPES_REDIS_PREFIX}{user_object.id}',
            time=constants.FREE_SWIPES_COOLDOWN_SEC,
            value=reap_timestamp)
        return reap_timestamp

    async def get_swipe_reap_timestamp(self, user_object: models.User) \
            -> Optional[int]:
        """
        Returns the timestamp for when the free swipes can be reaped
        """
        reap_timestamp = await self.redis.get(
            f'{constants.FREE_SWIPES_REDIS_PREFIX}{user_object.id}')
        return int(reap_timestamp) if reap_timestamp else None


class UserService:
    def __init__(self,
                 db: Session = Depends(swipe.dependencies.db)):
        self.db = db
        self._storage = CloudStorage()

    def create_user(self,
                    user_payload: schemas.AuthenticationIn) -> models.User:
        auth_info = models.AuthInfo(**user_payload.dict())
        user_object = models.User()
        user_object.auth_info = auth_info

        self.db.add(auth_info)
        self.db.add(user_object)
        self.db.commit()
        self.db.refresh(user_object)
        return user_object

    def generate_random_user(self):
        new_user = self.create_user(AuthenticationIn(
            auth_provider=AuthProvider.SNAPCHAT,
            provider_token=secrets.token_urlsafe(16),
            provider_user_id=secrets.token_urlsafe(16)))
        self._update_location(new_user, {
            'city': 'Moscow',
            'country': 'Russia',
            'flag': '🇷🇺'
        })
        birth_date = datetime.date.today().replace(
            year=random.randint(1985, 2003),
            month=random.randint(1, 12),
            day=random.randint(1, 25))
        new_user.date_of_birth = birth_date
        new_user.zodiac_sign = ZodiacSign.from_date(birth_date)
        new_user.rating = random.randint(5, 150)

        self.db.add(new_user)
        self.db.commit()
        return new_user

    def get_user(self, user_id: UUID) -> Optional[models.User]:
        return self.db.execute(
            select(models.User).where(models.User.id == user_id)) \
            .scalar_one_or_none()

    def get_users(self) -> list[models.User]:
        return self.db.execute(select(models.User)).scalars().all()

    def _update_location(self,
                         user_object: models.User,
                         location: dict[str, str]):
        # location rows are unique with regards to city/country
        location_in_db = \
            self.db.execute(
                select(models.Location).
                    where(models.Location.city == location['city']).
                    where(models.Location.country == location['country'])). \
                scalar_one_or_none()

        if not location_in_db:
            location_in_db = models.Location(**location)
            self.db.add(location_in_db)

        user_object.location = location_in_db

    def update_user(
            self,
            user_object: models.User,
            user: schemas.UserUpdate) -> models.User:
        for k, v in user.dict(exclude_unset=True).items():
            if k == 'location':
                self._update_location(user_object, v)
            else:
                setattr(user_object, k, v)
        self.db.commit()
        self.db.refresh(user_object)
        return user_object

    def add_photo(self, user_object: models.User, file: UploadFile):
        _, _, extension = file.content_type.partition('/')
        image_id = f'{uuid.uuid4()}.{extension}'
        self._storage.upload_image(image_id, file.file)

        user_object.photos = user_object.photos + [image_id]
        self.db.commit()
        return image_id

    def delete_photo(self, user_object: models.User, photo_id: str):
        new_list = list(user_object.photos)
        new_list.remove(photo_id)
        user_object.photos = new_list

        self._storage.delete_image(photo_id)
        self.db.commit()

    def find_user_by_auth(
            self,
            user_payload: schemas.AuthenticationIn) -> Optional[models.User]:
        auth_info = self.db.execute(
            select(models.AuthInfo)
                .where(models.AuthInfo.auth_provider
                       == user_payload.auth_provider)
                .where(models.AuthInfo.provider_user_id
                       == user_payload.provider_user_id)) \
            .scalar_one_or_none()
        # TODO check queries for extra joins
        return auth_info.user if auth_info else None

    def create_access_token(self, user_object: models.User,
                            payload: schemas.AuthenticationIn) -> str:
        access_token = jwt.encode(
            schemas.JWTPayload(
                **payload.dict(),
                user_id=user_object.id,
                created_at=time.time_ns()
            ).dict(),
            settings.SWIPE_SECRET_KEY, algorithm=ALGORITHMS.HS256)
        user_object.auth_info.access_token = access_token
        self.db.commit()
        return access_token

    def add_swipes(self, user_object: models.User, swipe_number: int):
        if swipe_number < 0:
            raise ValueError("swipe_number must be positive")

        user_object.swipes += swipe_number
        self.db.commit()
        self.db.refresh(user_object)
        return user_object
