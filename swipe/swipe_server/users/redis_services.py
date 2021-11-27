import logging
import time
from dataclasses import dataclass
from typing import Optional, Tuple, AsyncGenerator
from uuid import UUID

from aioredis import Redis
from fastapi import Depends

from swipe.settings import settings, constants
from swipe.swipe_server.misc import dependencies
from swipe.swipe_server.misc.errors import SwipeError
from swipe.swipe_server.users.enums import Gender
from swipe.swipe_server.users.models import User, Location
from swipe.swipe_server.users.schemas import PopularFilterBody

logger = logging.getLogger(__name__)


@dataclass
class OnlineUserCacheParams:
    age: int
    country: str
    city: Optional[str] = None
    gender: Optional[Gender] = None

    def cache_key(self) -> str:
        gender = self.gender if self.gender else 'ALL'
        city = self.city if self.city else 'ALL'
        return f'online:{self.country}:{city}:{self.age}:{gender}'

    def online_keys(self):
        if not self.city or not self.gender:
            raise SwipeError("city and gender must be set")
        result = [
            f'online:{self.country}:{self.city}:{self.age}:ALL',
            f'online:{self.country}:ALL:{self.age}:ALL',
        ]
        if self.gender != Gender.ATTACK_HELICOPTER:
            # attack helicopters go only to ALL gender cache
            result.extend([
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


class RedisSwipeReapService:
    def __init__(self,
                 redis: Redis = Depends(dependencies.redis)):
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
    def __init__(self,
                 redis: Redis = Depends(dependencies.redis)):
        self.redis = redis

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


class RedisBlacklistService:
    BLACKLIST_KEY = 'blacklist'

    def __init__(self,
                 redis: Redis = Depends(dependencies.redis)):
        self.redis = redis

    async def filter_blacklist(self, current_user_id: UUID,
                               user_ids: set[str]) -> set[str]:
        if settings.ENABLE_BLACKLIST:
            blacklist: set[str] = await self.get_blacklist(current_user_id)
            return user_ids.difference(blacklist)
        return user_ids

    async def get_blacklist(self, user_id: UUID) -> set[str]:
        if settings.ENABLE_BLACKLIST:
            return await self.redis.smembers(f'{self.BLACKLIST_KEY}:{user_id}')
        return set()

    async def add_to_blacklist_cache(
            self, blocked_user_id: str, blocked_by_id: str):
        if settings.ENABLE_BLACKLIST:
            logger.info(f"Adding both {blocked_user_id} and {blocked_by_id}"
                        f"to each others blacklist cache")
            await self.redis.sadd(f'{self.BLACKLIST_KEY}:{blocked_user_id}',
                                  blocked_by_id)
            await self.redis.sadd(f'{self.BLACKLIST_KEY}:{blocked_by_id}',
                                  blocked_user_id)

    async def populate_blacklist(self, user_id: str, blacklist: set[str]):
        if settings.ENABLE_BLACKLIST:
            await self.redis.sadd(f'{self.BLACKLIST_KEY}:{user_id}', *blacklist)

    async def drop(self, user_id: str):
        if settings.ENABLE_BLACKLIST:
            await self.redis.delete(f'{self.BLACKLIST_KEY}:{user_id}')


class RedisOnlineUserService:

    def __init__(self,
                 redis: Redis = Depends(dependencies.redis)):
        self.redis = redis

    async def get_online_users(self, cache_params: OnlineUserCacheParams) \
            -> set[str]:
        return await self.redis.smembers(cache_params.cache_key())

    async def connect_user(self, user: User):
        # add to all online sets
        cache_params = OnlineUserCacheParams(
            age=user.age,
            country=user.location.country,
            city=user.location.city,
            gender=user.gender
        )
        for key in cache_params.online_keys():
            await self.redis.sadd(key, str(user.id))

    async def disconnect_user(self, user: User):
        cache_params = OnlineUserCacheParams(
            age=user.age,
            country=user.location.country,
            city=user.location.city,
            gender=user.gender
        )
        # removing this user from all online caches
        for key in cache_params.online_keys():
            await self.redis.srem(key, str(user.id))

    async def invalidate_online_user_cache(self):
        for key in await self.redis.keys('online:*'):
            await self.redis.delete(key)

    # --------------------------------------------
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

    async def drop_all_response_caches(self, user_id: Optional[str] = None):
        for key in await self.redis.keys(f'{FETCH_REQUEST_KEY}:*'):
            await self.redis.delete(key)

        if not user_id:
            return

        for key in await self.redis.keys(f'{FETCH_REQUEST_KEY}:{user_id}:*'):
            await self.redis.delete(key)

    # --------------------------------------------
    async def update_user_location(
            self, user: User, previous_location: Location):
        cache_params = OnlineUserCacheParams(
            age=user.age,
            country=previous_location.country,
            city=previous_location.city,
            gender=user.gender
        )
        # removing this user from all online caches
        for key in cache_params.online_keys():
            await self.redis.srem(key, str(user.id))

        # putting him back to caches with correct location
        await self.connect_user(user)