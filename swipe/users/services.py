import datetime
import io
import logging
import random
import secrets
import time
import uuid
from typing import Optional
from uuid import UUID

import lorem
import names
from aioredis import Redis
from dateutil.relativedelta import relativedelta
from fastapi import Depends
from jose import jwt
from jose.constants import ALGORITHMS
from sqlalchemy import select
from sqlalchemy.orm import Session

import swipe.dependencies
from settings import settings, constants
from swipe import images
from swipe.storage import CloudStorage
from swipe.users import schemas
from swipe.users.enums import AuthProvider, ZodiacSign, Gender, UserInterests, \
    RecurrenceRate
from swipe.users.models import IDList, User, AuthInfo, Location
from swipe.users.schemas import AuthenticationIn

logger = logging.getLogger(__name__)


class RedisService:
    def __init__(self,
                 redis: Redis = Depends(swipe.dependencies.redis)):
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

    async def filter_online_users(self, user_ids: IDList) -> IDList:
        result: IDList = []
        for user_id in user_ids:
            # TODO cache online users in memory and use set intersections
            is_online = await self.redis.get(
                f'{constants.ONLINE_USER_PREFIX}{user_id}')
            if is_online:
                result.append(user_id)
        return result

    async def is_online(self, user_id: UUID) -> IDList:
        return await self.redis.get(
            f'{constants.ONLINE_USER_PREFIX}{user_id}')

    async def refresh_online_status(
            self, user: User,
            ttl: int = constants.ONLINE_USER_COOLDOWN_SEC):
        await self.redis.setex(
            f'{constants.ONLINE_USER_PREFIX}{user.id}',
            time=ttl, value=1)


class UserService:
    def __init__(self,
                 db: Session = Depends(swipe.dependencies.db)):
        self.db = db
        self._storage = CloudStorage()

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

    def generate_random_user(self,
                             generate_images: bool = False):
        new_user = self.create_user(AuthenticationIn(
            auth_provider=AuthProvider.SNAPCHAT,
            provider_user_id=secrets.token_urlsafe(16)))
        new_user.name = names.get_full_name()
        new_user.bio = lorem.paragraph()[:200]
        new_user.height = random.randint(150, 195)
        new_user.interests = list({
            random.choice(list(UserInterests)) for _ in range(6)
        })[:3]
        new_user.gender = random.choice(list(Gender))
        new_user.smoking = random.choice(list(RecurrenceRate))
        new_user.drinking = random.choice(list(RecurrenceRate))

        birth_date = datetime.date.today().replace(
            year=random.randint(1985, 2003),
            month=random.randint(1, 12),
            day=random.randint(1, 25))
        new_user.date_of_birth = birth_date
        new_user.zodiac_sign = ZodiacSign.from_date(birth_date)
        new_user.rating = random.randint(5, 150)
        new_user.swipes = random.randint(50, 150)
        new_user.set_location({
            'city': random.choice([
                'Moscow', 'Saint Petersburg', 'Magadan', 'Surgut', 'Cherepovets'
            ]),
            'country': 'Russia',
            'flag': '🇷🇺'
        })
        self.db.add(new_user)
        self.db.commit()
        self.db.refresh(new_user)

        number_of_images = 4 if generate_images else 0
        for _ in range(number_of_images):
            image = images.generate_random_avatar(new_user.name)
            with io.BytesIO() as output:
                image.save(output, format='png')
                contents = output.getvalue()
                self.add_photo(new_user, contents, 'png')

        return new_user

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

    def update_user(
            self,
            user_object: User,
            user_update: schemas.UserUpdate) -> User:
        for k, v in user_update.dict(exclude_unset=True).items():
            if k == 'location':
                user_object.set_location(v)
            else:
                setattr(user_object, k, v)
        self.db.commit()
        self.db.refresh(user_object)
        return user_object

    def add_photo(self, user_object: User, file_content: bytes,
                  extension: str) -> str:
        image_id = f'{uuid.uuid4()}.{extension}'
        self._storage.upload_image(image_id, file_content)

        user_object.photos = user_object.photos + [image_id]
        self.db.commit()
        return image_id

    def delete_photo(self, user_object: User, photo_id: str):
        new_list = list(user_object.photos)
        new_list.remove(photo_id)
        user_object.photos = new_list

        self._storage.delete_image(photo_id)
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
