import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Tuple, AsyncGenerator, Iterable
from uuid import UUID

from aioredis import Redis
from fastapi import Depends

from swipe.settings import settings, constants
from swipe.swipe_server.misc import dependencies
from swipe.swipe_server.misc.errors import SwipeError
from swipe.swipe_server.users.enums import Gender
from swipe.swipe_server.users.models import User, Location
from swipe.swipe_server.users.schemas import PopularFilterBody, \
    UserCardPreviewOut
from swipe.swipe_server.utils import enable_blacklist

logger = logging.getLogger(__name__)


@dataclass
class OnlineUserCacheParams:
    age: int
    country: Optional[str] = None
    city: Optional[str] = None
    gender: Optional[Gender] = None

    def cache_key(self) -> str:
        gender = self.gender or 'ALL'
        city = self.city or 'ALL'
        country = self.country or 'ALL'
        return f'online:{country}:{city}:{self.age}:{gender}'

    def online_keys(self):
        if not self.city or not self.gender or not self.country:
            raise SwipeError("country, city and gender must be set")

        result = [
            f'online:{self.country}:{self.city}:{self.age}:ALL',
            f'online:{self.country}:ALL:{self.age}:ALL',
            f'online:ALL:ALL:{self.age}:ALL',
        ]
        if self.gender != Gender.ATTACK_HELICOPTER:
            # attack helicopters go only to ALL gender cache
            result.extend([
                f'online:ALL:ALL:{self.age}:{self.gender}',
                f'online:{self.country}:ALL:{self.age}:{self.gender}',
                f'online:{self.country}:{self.city}:{self.age}:{self.gender}'
            ])
        return result


FETCH_REQUEST_KEY = 'fetch_request'


@dataclass
class FetchUserCacheKey:
    user_id: str
    session_id: str

    def cache_key(self):
        return f'{FETCH_REQUEST_KEY}:{self.user_id}:{self.session_id}'

    def key_user_wildcard(self):
        return f'{FETCH_REQUEST_KEY}:{self.user_id}:*'


class RedisSwipeReaperService:
    FREE_SWIPES_REDIS_PREFIX = 'free_swipes_cooldown'

    def __init__(self,
                 redis: Redis = Depends(dependencies.redis)):
        self.redis = redis

    async def reset_swipe_reap_timestamp(self, user_id: UUID) -> datetime:
        """
        Sets the timestamp for when the free swipes can be reaped
        for the specified user
        """
        # this "optional parameter" junk is required only so that
        # I could test the method

        reap_date = datetime.utcnow() + timedelta(
            seconds=constants.SWIPES_REAP_TIMEOUT_SEC)
        reap_date = reap_date.replace(microsecond=0)

        await self.redis.setex(
            f'{self.FREE_SWIPES_REDIS_PREFIX}:{user_id}',
            time=constants.SWIPES_REAP_TIMEOUT_SEC,
            value=int(reap_date.timestamp()))

        return reap_date

    async def get_swipe_reap_timestamp(self, user_id: UUID) \
            -> Optional[datetime]:
        """
        Returns the timestamp for when the free swipes can be reaped
        """
        reap_timestamp = await self.redis.get(
            f'{self.FREE_SWIPES_REDIS_PREFIX}:{str(user_id)}')
        return datetime.fromtimestamp(int(reap_timestamp)) \
            if reap_timestamp else None


class RedisLocationService:
    def __init__(self,
                 redis: Redis = Depends(dependencies.redis)):
        self.redis = redis

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


class RedisPopularService:
    POPULAR_LIST_KEY = 'popular'
    POPULAR_USER_KEY = 'popular_user'

    def __init__(self,
                 redis: Redis = Depends(dependencies.redis)):
        self.redis = redis

    async def get_popular_user_ids(self, filter_params: PopularFilterBody) \
            -> list[str]:
        gender = filter_params.gender or 'ALL'
        city = filter_params.city or 'ALL'
        country = filter_params.country or 'ALL'
        key = f'{self.POPULAR_LIST_KEY}:{gender}:country:{country}:city:{city}'

        logger.info(f"Getting popular for key {key}")
        return await self.redis.lrange(
            key, filter_params.offset,
            filter_params.offset + filter_params.limit - 1)

    async def save_popular_users(self,
                                 users: list[User],
                                 country: Optional[str] = None,
                                 gender: Optional[Gender] = None,
                                 city: Optional[str] = None):
        if not users:
            return
        gender = gender or 'ALL'
        city = city or 'ALL'
        country = country or 'ALL'
        key = f'{self.POPULAR_LIST_KEY}:{gender}:country:{country}:city:{city}'
        logger.info(f"Deleting and saving popular cache "
                    f"of {len(users)} users for {key}")

        await self.redis.delete(key)
        for user in users:
            await self.redis.rpush(key, str(user.id))
            try:
                json_data = UserCardPreviewOut.patched_from_orm(user).json()
            except:
                logger.exception(f"{user.id} won't be added to popular list "
                                 f"because the model is broken")
            else:
                # TODO man, I need a separate connection without decoding
                # but I don't wanna do that atm
                # json_data = zlib.compress(json_data.encode('utf-8'))
                await self.redis.set(
                    f'{self.POPULAR_USER_KEY}:{user.id}', json_data)

    async def get_user_card_previews(self, user_ids: Iterable[str]) \
            -> list[str]:
        return await self.redis.mget([
            f'{self.POPULAR_USER_KEY}:{user_id}' for user_id in user_ids
        ])


class RedisBlacklistService:
    BLACKLIST_KEY = 'blacklist'

    def __init__(self,
                 redis: Redis = Depends(dependencies.redis)):
        self.redis = redis

    @enable_blacklist(return_value_class=set)
    async def get_blacklist(self, user_id: str) -> set[str]:
        return await self.redis.smembers(f'{self.BLACKLIST_KEY}:{user_id}')

    @enable_blacklist()
    async def add_to_blacklist_cache(
            self, blocked_user_id: str, blocked_by_id: str):
        logger.info(f"Adding both {blocked_user_id} and {blocked_by_id}"
                    f"to each others blacklist cache")
        await self.redis.sadd(f'{self.BLACKLIST_KEY}:{blocked_user_id}',
                              blocked_by_id)
        await self.redis.sadd(f'{self.BLACKLIST_KEY}:{blocked_by_id}',
                              blocked_user_id)

    @enable_blacklist()
    async def populate_blacklist(self, user_id: str, blacklist: set[str]):
        await self.redis.sadd(f'{self.BLACKLIST_KEY}:{user_id}', *blacklist)

    @enable_blacklist()
    async def drop_blacklist_cache(self, user_id: str):
        await self.redis.delete(f'{self.BLACKLIST_KEY}:{user_id}')


class RedisOnlineUserService:
    RECENTLY_ONLINE_KEY = 'recently_online_user'
    ONLINE_USER_KEY = 'online_user'

    def __init__(self,
                 redis: Redis = Depends(dependencies.redis)):
        self.redis = redis

    async def get_online_users(self, cache_params: OnlineUserCacheParams) \
            -> set[str]:
        return await self.redis.smembers(cache_params.cache_key())

    async def add_to_online_caches(self, user: User):
        # add to all online sets
        cache_params = OnlineUserCacheParams(
            age=user.age,
            country=user.location.country,
            city=user.location.city,
            gender=user.gender
        )
        user_id = str(user.id)
        for key in cache_params.online_keys():
            await self.redis.sadd(key, user_id)

        json_data = UserCardPreviewOut.patched_from_orm(user).json()
        # TODO man, I need a separate connection without decoding
        # but I don't wanna do that atm
        # json_data = zlib.compress(json_data.encode('utf-8'))

        await self.redis.set(f'{self.ONLINE_USER_KEY}:{user.id}', json_data)

    async def remove_from_online_caches(
            self, user: User, location: Optional[Location] = None):
        country = location.country if location else user.location.country
        city = location.city if location else user.location.city
        cache_params = OnlineUserCacheParams(
            age=user.age, country=country, city=city, gender=user.gender)
        # removing this user from all online caches
        user_id = str(user.id)
        for key in cache_params.online_keys():
            await self.redis.srem(key, user_id)

        await self.redis.delete(f'{self.ONLINE_USER_KEY}:{user.id}')

    async def invalidate_online_user_cache(self):
        for key in await self.redis.keys('online:*'):
            await self.redis.delete(key)

    async def update_recently_online_cache(
            self, recently_online_ttl=constants.RECENTLY_ONLINE_TTL_SEC):
        for key in await self.redis.keys(f'{self.RECENTLY_ONLINE_KEY}:*'):
            user_data = await self.redis.get(key)
            user_data = json.loads(user_data)
            # dude's been gone for too long
            online_time_diff = (int(time.time()) - user_data['last_online'])
            if online_time_diff > recently_online_ttl:
                # removing this dude from the recently_online list
                await self.redis.delete(key)

                cache_params = OnlineUserCacheParams(
                    age=user_data['age'], country=user_data['country'],
                    city=user_data['city'], gender=user_data['gender'])
                user_id = str(key).split(":")[1]

                # removing this dude from all online caches
                for online_key in cache_params.online_keys():
                    await self.redis.srem(online_key, user_id)

    async def add_to_recently_online_cache(self, user: User):
        last_online = datetime.utcnow()
        user_data = {
            # I'm intentionally not using field value from user object
            'last_online': int(last_online.timestamp()),
            'age': user.age,
            'country': user.location.country,
            'city': user.location.city,
            'gender': user.gender.value
        }
        # user_data = zlib.compress(json.dumps(user_data).encode('utf-8'))
        await self.redis.set(
            f'{self.RECENTLY_ONLINE_KEY}:{user.id}', json.dumps(user_data))

        # update last_online field here so that we could sort these entities
        # without touching the cache again
        cached_user = await self.redis.get(f'{self.ONLINE_USER_KEY}:{user.id}')
        cached_user = json.loads(cached_user)
        cached_user['last_online'] = last_online.isoformat()
        await self.redis.set(f'{self.ONLINE_USER_KEY}:{user.id}',
                             json.dumps(cached_user))

    async def remove_from_recently_online(self, user_id: str):
        await self.redis.delete(f'{self.RECENTLY_ONLINE_KEY}:{user_id}')

    async def get_user_card_previews(self, user_ids: Iterable[str]) \
            -> Iterable[str]:
        return await self.redis.mget([
            f'{self.ONLINE_USER_KEY}:{user_id}' for user_id in user_ids
        ])


class RedisUserFetchService:
    def __init__(self,
                 redis: Redis = Depends(dependencies.redis)):
        self.redis = redis

    async def get_response_cache(
            self, cache_settings: FetchUserCacheKey) \
            -> set[str]:
        if await self.redis.exists(cache_settings.cache_key()):
            return await self.redis.smembers(cache_settings.cache_key())

        return set()

    async def drop_obsolete_caches(
            self, cache_settings: FetchUserCacheKey):
        if not await self.redis.exists(cache_settings.cache_key()):
            # no key with current session
            # but there is an older one
            if await self.redis.keys(cache_settings.key_user_wildcard()):
                logger.info(
                    f"Removing previous cache for {cache_settings.user_id}")
                # drop other requests for other session_ids
                await self.drop_response_cache(cache_settings.user_id)

    async def add_to_response_cache(
            self, cache_settings: FetchUserCacheKey,
            current_user_ids: set[str]):
        if not current_user_ids:
            return

        await self.redis.sadd(cache_settings.cache_key(), *current_user_ids)
        # failsafe, 1 hours
        await self.redis.expire(
            cache_settings.cache_key(), settings.ONLINE_USER_RESPONSE_CACHE_TTL)

    async def drop_response_cache(self, user_id: str):
        for key in await self.redis.keys(f'{FETCH_REQUEST_KEY}:{user_id}:*'):
            await self.redis.delete(key)

    async def drop_fetch_response_caches(self, user_id: Optional[str] = None):
        for key in await self.redis.keys(f'{FETCH_REQUEST_KEY}:*'):
            await self.redis.delete(key)

        if not user_id:
            return

        for key in await self.redis.keys(f'{FETCH_REQUEST_KEY}:{user_id}:*'):
            await self.redis.delete(key)
