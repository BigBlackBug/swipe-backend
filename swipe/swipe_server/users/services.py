import base64
import logging
import time
import uuid
from typing import Optional
from uuid import UUID

import requests
from aioredis import Redis
from dateutil.relativedelta import relativedelta
from fastapi import Depends
from jose import jwt
from jose.constants import ALGORITHMS
from sqlalchemy import select, delete
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

import swipe.swipe_server.misc.dependencies
from swipe.settings import settings, constants
from swipe.swipe_server import utils
from swipe.swipe_server.misc.errors import SwipeError
from swipe.swipe_server.misc.storage import storage_client
from swipe.swipe_server.users import schemas
from swipe.swipe_server.users.enums import Gender
from swipe.swipe_server.users.models import IDList, User, AuthInfo, Location

logger = logging.getLogger(__name__)


class RedisUserService:
    def __init__(self,
                 redis: Redis = Depends(
                     swipe.swipe_server.misc.dependencies.redis)):
        self.redis = redis

    async def reset_swipe_reap_timestamp(
            self, user_object: User) -> int:
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

    async def get_swipe_reap_timestamp(self, user_object: User) \
            -> Optional[int]:
        """
        Returns the timestamp for when the free swipes can be reaped
        """
        reap_timestamp = await self.redis.get(
            f'{constants.FREE_SWIPES_REDIS_PREFIX}{user_object.id}')
        return int(reap_timestamp) if reap_timestamp else None

    # TODO hello, copy/paste style
    async def filter_online_users(self, user_ids: IDList,
                                  status: bool = True) -> IDList:
        result: IDList = []
        for user_id in user_ids:
            # TODO cache online users in memory and use set intersections
            is_online = await self.is_online(user_id)
            if bool(is_online) == status:
                result.append(user_id)
        return result

    async def is_online(self, user_id: UUID) -> IDList:
        return await self.redis.get(
            f'{constants.ONLINE_USER_PREFIX}{user_id}')

    async def refresh_online_status(
            self, user_id: UUID,
            ttl: int = constants.ONLINE_USER_COOLDOWN_SEC):
        await self.redis.setex(
            f'{constants.ONLINE_USER_PREFIX}{user_id}',
            time=ttl, value=1)

    async def remove_online_user(self, user_id: UUID):
        await self.redis.delete(
            f'{constants.ONLINE_USER_PREFIX}{user_id}')


class UserService:
    def __init__(self,
                 db: Session = Depends(
                     swipe.swipe_server.misc.dependencies.db)):
        self.db = db

    def create_user(self,
                    user_payload: schemas.AuthenticationIn) -> User:
        auth_info = AuthInfo(**user_payload.dict())
        user_object = User()
        user_object.auth_info = auth_info

        self.db.add(auth_info)
        self.db.add(user_object)
        self.db.commit()
        self.db.refresh(user_object)
        return user_object

    def find_user_ids(self, current_user: User,
                      gender: Optional[Gender] = None,
                      age_difference: int = 0,
                      city: Optional[str] = None,
                      ignore_users: Optional[IDList] = None) -> IDList:
        """
        Return a list of user ids with regards to supplied filters

        :param current_user:
        :param gender: ignore if None
        :param age_difference:
        :param city: ignore if None
        :param ignore_users: user ids to exclude from query
        :return:
        """
        ignore_users = ignore_users if ignore_users else []
        city_clause = True if not city else Location.city == city
        gender_clause = True if not gender else User.gender == gender
        min_age = current_user.date_of_birth - relativedelta(
            years=age_difference)
        max_age = current_user.date_of_birth + relativedelta(
            years=age_difference)

        # all users are filtered by country
        query = select(User.id).join(User.location). \
            where(Location.country == current_user.location.country). \
            where(city_clause). \
            where(gender_clause). \
            where(User.date_of_birth.between(min_age, max_age)). \
            where(User.id != current_user.id). \
            where(~User.id.in_(ignore_users)). \
            where(~User.blocked_by.any(id=current_user.id))
        return self.db.execute(query).scalars().all()

    def get_user(self, user_id: UUID) -> Optional[User]:
        return self.db.execute(
            select(User).where(User.id == user_id)) \
            .scalar_one_or_none()

    def get_users(self, user_ids: Optional[IDList] = None) -> list[User]:
        clause = True if user_ids is None else User.id.in_(user_ids)
        return self.db.execute(select(User).where(clause)). \
            scalars().all()

    def get_user_chat_preview(
            self, user_ids: Optional[IDList] = None,
            location: bool = False) -> list[Row]:
        clause = True if user_ids is None else User.id.in_(user_ids)
        if location:
            return self.db.execute(
                select(User.id, User.name, User.photos, Location).
                    join(Location).where(clause)).all()
        else:
            return self.db.execute(
                select(User.id, User.name, User.photos).where(clause)).all()

    def get_global_chat_preview(
            self, user_ids: Optional[IDList] = None) -> list[Row]:
        clause = True if user_ids is None else User.id.in_(user_ids)
        return self.db.execute(
            select(User.id, User.name, User.avatar).where(clause)).all()

    def get_global_chat_preview_one(self, user_id: UUID) -> Optional[Row]:
        return self.db.execute(
            select(User.id, User.name, User.avatar).
                where(User.id == user_id)).one_or_none()

    def update_user(
            self,
            user_object: User,
            user_update: schemas.UserUpdate) -> User:
        for k, v in user_update.dict(exclude_unset=True).items():
            if k == 'location':
                user_object.set_location(v)
            else:
                setattr(user_object, k, v)
                if k == 'photos':
                    if len(v) > 0:
                        self._update_avatar(user_object, photo_id=v[0])
                    else:
                        user_object.avatar = None
        self.db.commit()
        self.db.refresh(user_object)
        return user_object

    def _update_avatar(self, user: User, photo_id: Optional[str] = None,
                       image_content: Optional[bytes] = None):
        if photo_id:
            img_url = storage_client.get_image_url(photo_id)
            image_content = requests.get(img_url).content
        elif not image_content:
            raise SwipeError(
                "Either photo_id or image_content must be provided")

        compressed_image = utils.compress_image(image_content)
        user.avatar = base64.b64encode(compressed_image)

    def add_photo(self, user_object: User, file_content: bytes,
                  extension: str) -> str:
        photo_id = f'{uuid.uuid4()}.{extension}'
        storage_client.upload_image(photo_id, file_content)

        user_object.photos = user_object.photos + [photo_id]
        if len(user_object.photos) == 1:
            self._update_avatar(user_object, image_content=file_content)

        self.db.commit()
        return photo_id

    def delete_photo(self, user_object: User, photo_id: str):
        new_list = list(user_object.photos)
        index = new_list.index(photo_id)
        del new_list[index]

        user_object.photos = new_list
        if index == 0:
            self._update_avatar(user_object, photo_id=new_list[0])

        storage_client.delete_image(photo_id)
        self.db.commit()

    def find_user_by_auth(
            self,
            user_payload: schemas.AuthenticationIn) -> Optional[User]:
        auth_info = self.db.execute(
            select(AuthInfo)
                .where(AuthInfo.auth_provider
                       == user_payload.auth_provider)
                .where(AuthInfo.provider_user_id
                       == user_payload.provider_user_id)) \
            .scalar_one_or_none()
        # TODO check queries for extra joins
        return auth_info.user if auth_info else None

    def create_access_token(self, user_object: User,
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

    def add_swipes(self, user_object: User, swipe_number: int) -> User:
        if swipe_number < 0:
            raise ValueError("swipe_number must be positive")
        logger.info(f"Adding {swipe_number} swipes")

        user_object.swipes += swipe_number
        self.db.commit()
        self.db.refresh(user_object)
        return user_object

    def get_photo_url(self, image_id: str):
        return storage_client.get_image_url(image_id)

    def delete_user(self, user: User):
        logger.info(f"Deleting user {user.id}")
        user.delete_photos()
        self.db.execute(delete(User).where(User.id == user.id))
        self.db.commit()

    def get_firebase_token(self, user_id: UUID):
        return self.db.execute(select(User.firebase_token).
                               where(User.id == user_id)).scalar_one_or_none()
