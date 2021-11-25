import datetime
import logging
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Union, Tuple, AsyncGenerator, Iterable
from uuid import UUID

import requests
from aioredis import Redis
from dateutil.relativedelta import relativedelta
from fastapi import Depends
from jose import jwt
from jose.constants import ALGORITHMS
from sqlalchemy import select, delete, func, desc, String, cast, insert
from sqlalchemy.engine import Row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, Bundle

import swipe.swipe_server.misc.dependencies
from swipe.settings import settings, constants
from swipe.swipe_server import utils
from swipe.swipe_server.misc.errors import SwipeError
from swipe.swipe_server.misc.storage import storage_client
from swipe.swipe_server.users import schemas
from swipe.swipe_server.users.enums import Gender
from swipe.swipe_server.users.models import IDList, User, AuthInfo, Location, \
    blacklist_table
from swipe.swipe_server.users.schemas import PopularFilterBody, OnlineFilterBody

logger = logging.getLogger(__name__)


@dataclass
class UserRequestCacheParams:
    age: int
    age_diff: int
    current_country: str
    gender_filter: Optional[str] = None
    city_filter: Optional[str] = None

    def cache_key(self):
        gender = self.gender_filter if self.gender_filter else 'ALL'
        return f'users:{self.age}:{self.age_diff}:{gender}:' \
               f'{self.current_country}:{self.city_filter}'


class KeyType(Enum):
    ONLINE_REQUEST = 'online_request'
    CARDS_REQUEST = 'cards_request'


@dataclass
class UserRequestCacheSettings:
    key_type: KeyType
    user_id: str
    city_filter: str
    gender_filter: Optional[str] = None

    def cache_key(self):
        gender = self.gender_filter if self.gender_filter else 'ALL'
        return f'{self.key_type.value}:{self.user_id}:' \
               f'{gender}:{self.city_filter}'


class RedisUserService:
    ONLINE_USERS_SET = 'online_users'
    BLACKLIST_KEY = 'blacklist'

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

    # ------------------------------------------------------------
    async def filter_online_users(self, user_ids: set[str]) -> set[str]:
        online_users: set[str] = await self.get_online_users()
        return user_ids.intersection(online_users)

    async def get_online_users(self) -> set[str]:
        return await self.redis.smembers(self.ONLINE_USERS_SET)

    async def is_online(self, user_id: UUID) -> bool:
        return await self.redis.sismember(self.ONLINE_USERS_SET, str(user_id))

    async def connect_user(self, user_id: UUID):
        await self.redis.sadd(self.ONLINE_USERS_SET, str(user_id))

    async def disconnect_user(self, user_id: UUID):
        await self.redis.srem(self.ONLINE_USERS_SET, str(user_id))
        # remove blacklist cache
        await self.redis.delete(f'{self.BLACKLIST_KEY}:{user_id}')
        # remove online request cache
        await self.drop_online_response_cache(
            str(user_id), KeyType.ONLINE_REQUEST)
        # remove online request cache
        await self.drop_online_response_cache(
            str(user_id), KeyType.CARDS_REQUEST)

    async def invalidate_online_user_cache(self):
        await self.redis.delete(self.ONLINE_USERS_SET)

    # -----------------------------------------
    async def drop_country_cache(self):
        countries = await self.redis.keys("country:*")
        if countries:
            await self.redis.delete(*countries)

    async def add_cities(self, country: str, cities: list[str]):
        await self.redis.sadd(f'country:{country}', *cities)

    async def fetch_locations(self) \
            -> AsyncGenerator[Tuple[str, list[str]], None]:
        countries = await self.redis.keys("country:*")
        for country_key in countries:
            country = country_key.split(":")[1]
            yield country, await self.redis.smembers(country_key)

    # ------------------------------------------------
    async def get_popular_users(self, filter_params: PopularFilterBody) \
            -> list[str]:
        gender = filter_params.gender if filter_params.gender else 'ALL'
        key = f'popular:{gender}:country:{filter_params.country}:' \
              f'city:{filter_params.city}'

        logger.info(f"Getting popular for key {key}")
        return await self.redis.lrange(
            key, filter_params.offset,
            filter_params.offset + filter_params.limit - 1)

    async def save_popular_users(self,
                                 users: list[str],
                                 country: str,
                                 gender: Optional[Gender] = None,
                                 city: Optional[str] = None):
        if not users:
            return
        gender = gender if gender else 'ALL'
        key = f'popular:{gender}:country:{country}:city:{city}'
        logger.info(f"Deleting and saving popular cache for {key}")

        await self.redis.delete(key)
        await self.redis.rpush(key, *users)

    # -------------------------------------------------------
    async def filter_blacklist(self, current_user_id: UUID,
                               user_ids: set[str]) -> set[str]:
        if settings.ENABLE_BLACKLIST:
            blacklist: set[str] = await self.get_blacklist(current_user_id)
            return user_ids.difference(blacklist)
        return user_ids

    async def get_blacklist(self, user_id: UUID) -> set[str]:
        return await self.redis.smembers(f'{self.BLACKLIST_KEY}:{user_id}')

    async def add_to_blacklist_cache(
            self, blocked_user_id: str, blocked_by_id: str):
        if settings.ENABLE_BLACKLIST:
            logger.info(f"adding both {blocked_user_id} and {blocked_by_id}"
                        f"to each others blacklist cache")
            await self.redis.sadd(f'{self.BLACKLIST_KEY}:{blocked_user_id}',
                                  blocked_by_id)
            await self.redis.sadd(f'{self.BLACKLIST_KEY}:{blocked_by_id}',
                                  blocked_user_id)

    async def populate_blacklist(self, user_id: str, blacklist: set[str]):
        if settings.ENABLE_BLACKLIST:
            await self.redis.sadd(f'{self.BLACKLIST_KEY}:{user_id}', *blacklist)

    # --------------------------------------------
    async def get_cached_online_response(
            self, cache_settings: UserRequestCacheSettings) \
            -> set[str]:
        return await self.redis.smembers(cache_settings.cache_key())

    async def add_cached_online_response(
            self, cache_settings: UserRequestCacheSettings,
            current_user_ids: set[str]):
        if not current_user_ids:
            return

        await self.redis.sadd(cache_settings.cache_key(), *current_user_ids)
        # failsafe
        await self.redis.expire(
            cache_settings.cache_key(), settings.ONLINE_USER_RESPONSE_CACHE_TTL)

    async def drop_online_response_cache(self, user_id: str, key_type: KeyType):
        for key in await self.redis.keys(f'{key_type.value}:{user_id}:*'):
            await self.redis.delete(key)

    async def drop_online_response_cache_all(self):
        for key in await self.redis.keys(f'{KeyType.ONLINE_REQUEST.value}:*'):
            await self.redis.delete(key)
        for key in await self.redis.keys(f'{KeyType.CARDS_REQUEST.value}:*'):
            await self.redis.delete(key)

    # --------------------------------------------
    async def find_user_ids(self,
                            cache_settings: UserRequestCacheParams) \
            -> Optional[set[str]]:
        return await self.redis.smembers(cache_settings.cache_key())

    async def store_user_ids(self,
                             cache_settings: UserRequestCacheParams,
                             current_user_ids: set[str]):
        if current_user_ids:
            await self.redis.delete(cache_settings.cache_key())
            await self.redis.sadd(cache_settings.cache_key(), *current_user_ids)
            await self.redis.expire(cache_settings.cache_key(),
                                    time=settings.USER_CACHE_TTL_SECS)

    async def remove_from_request_caches(
            self, user: User, previous_location: Location):
        gender = 'ALL' if user.gender == Gender.ATTACK_HELICOPTER \
            else user.gender.value
        age_delta = relativedelta(
            datetime.date.today(), user.date_of_birth)
        age = round(age_delta.years + age_delta.months / 12)
        user_id = str(user.id)

        for key in await self.redis.keys(
                f"users:*:*:{gender}:{previous_location.country}:"
                f"{previous_location.city}"):

            cache_settings = UserRequestCacheParams(
                age=int(key.split(':')[1]),
                age_diff=int(key.split(':')[2]),
                current_country=previous_location.country,
                gender_filter=gender,
                city_filter=previous_location.city
            )
            if cache_settings.age - cache_settings.age_diff <= \
                    age <= cache_settings.age + cache_settings.age_diff:
                logger.info(
                    f"Removing {user_id} from cache "
                    f"{cache_settings.cache_key()}")
                await self.redis.srem(cache_settings.cache_key(), user_id)

        for key in await self.redis.keys(
                f"users:*:*:{gender}:{previous_location.country}:None"):
            cache_settings = UserRequestCacheParams(
                age=int(key.split(':')[1]),
                age_diff=int(key.split(':')[2]),
                current_country=previous_location.country,
                gender_filter=gender
            )
            if cache_settings.age - cache_settings.age_diff <= \
                    age <= cache_settings.age + cache_settings.age_diff:
                logger.info(
                    f"Adding {user_id} to cache "
                    f"{cache_settings.cache_key()}")
                await self.redis.srem(cache_settings.cache_key(), user_id)

    async def add_user_to_request_caches(self, user: User):
        gender = 'ALL' if user.gender == Gender.ATTACK_HELICOPTER \
            else user.gender.value
        age_delta = relativedelta(
            datetime.date.today(), user.date_of_birth)
        age = round(age_delta.years + age_delta.months / 12)
        user_id = str(user.id)

        for key in await self.redis.keys(
                f"users:*:*:{gender}:{user.location.country}:"
                f"{user.location.city}"):

            cache_settings = UserRequestCacheParams(
                age=int(key.split(':')[1]),
                age_diff=int(key.split(':')[2]),
                current_country=user.location.country,
                gender_filter=gender,
                city_filter=user.location.city
            )
            if cache_settings.age - cache_settings.age_diff <= \
                    age <= cache_settings.age + cache_settings.age_diff:
                logger.info(
                    f"Adding {user_id} to cache "
                    f"{cache_settings.cache_key()}")
                await self.redis.sadd(cache_settings.cache_key(), user_id)

        for key in await self.redis.keys(
                f"users:*:*:{gender}:{user.location.country}:None"):
            cache_settings = UserRequestCacheParams(
                age=int(key.split(':')[1]),
                age_diff=int(key.split(':')[2]),
                current_country=user.location.country,
                gender_filter=gender,
                city_filter=None
            )
            if cache_settings.age - cache_settings.age_diff <= \
                    age <= cache_settings.age + cache_settings.age_diff:
                logger.info(
                    f"Adding {user_id} to cache "
                    f"{cache_settings.cache_key()}")
                await self.redis.sadd(cache_settings.cache_key(), user_id)

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
                      city: Optional[str] = None) -> set[str]:
        """
        Return a list of user ids with regards to supplied filters

        :param current_user:
        :param gender: ignore if None
        :param age_difference:
        :param city: ignore if None
        :return:
        """
        city_clause = True if not city else Location.city == city
        gender_clause = True if not gender else User.gender == gender
        min_age = current_user.date_of_birth - relativedelta(
            years=age_difference)
        max_age = current_user.date_of_birth + relativedelta(
            years=age_difference)

        query = select(cast(User.id, String)).join(User.location). \
            where(Location.country == current_user.location.country). \
            where(city_clause). \
            where(gender_clause). \
            where(User.id != current_user.id). \
            where(User.date_of_birth.between(min_age, max_age))

        return self.db.execute(query).scalars().all()

    def get_user(self, user_id: UUID) -> Optional[User]:
        return self.db.execute(
            select(User).where(User.id == user_id)) \
            .scalar_one_or_none()

    def get_users(self, current_user_id: UUID,
                  user_ids: Optional[
                      Union[Iterable[UUID], Iterable[str]]] = None) \
            -> list[User]:
        # TODO use load_only for card preview
        clause = True if user_ids is None else User.id.in_(user_ids)
        return self.db.execute(select(User).where(clause)
                               .where(User.id != current_user_id)). \
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
            select(User.id, User.name, User.avatar_id).where(clause)).all()

    def get_global_chat_preview_one(self, user_id: UUID) -> Optional[Row]:
        return self.db.execute(
            select(User.id, User.name, User.avatar_id).
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
                    logger.info(f"Deleting old avatar image "
                                f"{user_object.avatar_id}")
                    storage_client.delete_image(user_object.avatar_id)
                    if len(v) > 0:
                        self._update_avatar(user_object, photo_id=v[0])
                    else:
                        user_object.avatar_id = None
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

        avatar_id = f'{uuid.uuid4()}.png'

        compressed_image = utils.compress_image(image_content)
        storage_client.upload_image(avatar_id, compressed_image)
        user.avatar_id = avatar_id

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

    def fetch_locations(self) -> dict[str, list]:
        """
        Returns rows of cities grouped by country.
        Each row has two fields: row.country.country
            and grouped cities: row.cities
        :return: A list of rows.
        """
        query = select(Bundle("country", Location.country),
                       Bundle("cities",
                              func.array_agg(Location.city))).group_by(
            Location.country)
        query_result = self.db.execute(query)
        result = dict()
        for row in query_result.all():
            result[row.country.country] = list(row.cities)[0]
        return result

    def fetch_popular(self, country: str,
                      gender: Optional[Gender] = None,
                      city: Optional[str] = None,
                      limit: int = 100) -> list[str]:
        city_clause = True if not city else Location.city == city
        gender_clause = True if not gender else User.gender == gender
        query = select(cast(User.id, String)).join(User.location). \
            where(Location.country == country). \
            where(gender_clause). \
            where(city_clause). \
            order_by(desc(User.rating)).limit(limit)
        return self.db.execute(query).scalars().all()

    def update_blacklist(self, blocked_by_id: str, blocked_user_id: str):
        if settings.ENABLE_BLACKLIST:
            logger.info(f"Adding both {blocked_by_id} and {blocked_user_id}"
                        f"to each others blacklist")
            try:
                self.db.execute(insert(blacklist_table).values(
                    blocked_user_id=blocked_user_id,
                    blocked_by_id=blocked_by_id))
                self.db.commit()
            except IntegrityError:
                raise SwipeError(f"{blocked_user_id} is "
                                 f"already blocked by {blocked_by_id}")

    def fetch_blacklist(self, user_id: str) -> set[str]:
        if settings.ENABLE_BLACKLIST:
            return set(self.db.execute(
                select(cast(blacklist_table.columns.blocked_user_id, String))
                    .where(blacklist_table.columns.blocked_by_id == user_id)
            ).scalars())
        return set()


class CacheService:
    def __init__(self, user_service: UserService,
                 redis_service: RedisUserService):
        self.user_service = user_service
        self.redis_service = redis_service

    async def _fill_cache(self, country, city: Optional[str] = None,
                          gender: Optional[Gender] = None):
        users = self.user_service.fetch_popular(
            country=country, city=city, gender=gender)
        logger.info(
            f"Got {len(users)} popular users from db for: "
            f"{country}, {city}, {gender}")
        await self.redis_service.save_popular_users(
            country=country, city=city, gender=gender, users=users)

    async def populate_popular_cache(self):
        logger.info("Populating popular cache")

        locations = self.redis_service.fetch_locations()
        async for country, cities in locations:
            logger.info(f"Processing country: '{country}'")
            await self._fill_cache(country, gender=Gender.MALE)
            await self._fill_cache(country, gender=Gender.FEMALE)
            await self._fill_cache(country)

            logger.info(f"Processing cities cache - '{country}', "
                        f"cities: '{cities}'")
            for city in cities:
                await self._fill_cache(country, city=city, gender=Gender.MALE)
                await self._fill_cache(country, city=city, gender=Gender.FEMALE)
                await self._fill_cache(country, city=city)

    async def populate_country_cache(self):
        locations = self.user_service.fetch_locations()

        logger.info("Dropping country cache")
        await self.redis_service.drop_country_cache()

        logger.info(f"Populating location cache with locations: {locations}")
        for country, cities in locations.items():
            logger.info(f"Saving {cities} to {country}")
            await self.redis_service.add_cities(country, cities)


class FetchService:
    def __init__(self, user_service: UserService = Depends(),
                 redis_service: RedisUserService = Depends()):
        self.user_service = user_service
        self.redis_service = redis_service

    async def collect(self, current_user: User,
                      filter_params: OnlineFilterBody,
                      key_type: KeyType) -> set[str]:
        user_cache = UserRequestCacheSettings(
            key_type=key_type,
            user_id=str(current_user.id),
            gender_filter=filter_params.gender,
            city_filter=filter_params.city
        )
        age_delta = relativedelta(datetime.date.today(),
                                  current_user.date_of_birth)
        age = round(age_delta.years + age_delta.months / 12)

        collected_user_ids: set[str] = set()

        # the user's been away from the screen for too long or changed settings
        # let's start from the beginning
        if filter_params.invalidate_cache:
            ignored_user_ids: set[str] = set()
            await self.redis_service.drop_online_response_cache(
                str(current_user.id), key_type=user_cache.key_type)
            logger.info(f"User {current_user.id} request cache invalidated")
        else:
            # previously fetched users will be ignored
            ignored_user_ids: set[str] = \
                await self.redis_service.get_cached_online_response(user_cache)
            logger.info(
                f"User request cache, key:{user_cache.cache_key()}, "
                f"{ignored_user_ids}")

        age_difference = settings.ONLINE_USER_DEFAULT_AGE_DIFF

        logger.info(f"Got filter params {filter_params}")
        # FEED filtered by same country by default)
        # premium filtered by gender
        # premium filtered by location(whole country/my city)
        blacklist = await self.redis_service.get_blacklist(current_user.id)
        online = await self.redis_service.get_online_users()
        while len(collected_user_ids) <= filter_params.limit:
            # saving caches for typical requests
            # I'm 25, give me users from Russia within 2 years of my age
            # this cache refers only to users in db as online-ness
            # is checked later
            cache_params = UserRequestCacheParams(
                age=age,
                age_diff=age_difference,
                current_country=current_user.location.country,
                gender_filter=filter_params.gender,
                city_filter=filter_params.city
            )
            current_user_ids: set[str] = \
                await self.redis_service.find_user_ids(cache_params)
            if not current_user_ids:
                logger.info(
                    f"Cache not found or empty for {cache_params.cache_key()}, "
                    f"querying database")

                current_user_ids = set(self.user_service.find_user_ids(
                    current_user, gender=filter_params.gender,
                    age_difference=age_difference,
                    city=filter_params.city))

                logger.info(
                    f"Got {collected_user_ids} "
                    f"for settings {cache_params.cache_key()}. "
                    f"Saving cache")
                await self.redis_service.store_user_ids(
                    cache_params, current_user_ids)

            # removing
            # and we're going through all these users, ugh
            for user in current_user_ids:
                # we need this filter because on each loop
                # we are fetching same users
                # TODO rework someday
                if user not in ignored_user_ids:
                    ignored_user_ids.add(user)
                    collected_user_ids.add(user)

            collected_user_ids = collected_user_ids.difference(blacklist)
            collected_user_ids = collected_user_ids.intersection(online)

            if age_difference >= settings.ONLINE_USER_MAX_AGE_DIFF:
                break

            # increasing search boundaries
            age_difference += settings.ONLINE_USER_AGE_DIFF_STEP

        logger.info(f"Adding {collected_user_ids} to user request cache "
                    f"for {user_cache.cache_key()}")
        # adding currently returned users to cache
        await self.redis_service.add_cached_online_response(
            user_cache, collected_user_ids)
        return collected_user_ids
