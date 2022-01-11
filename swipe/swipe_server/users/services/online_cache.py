import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Generic, Iterable, TypeVar

import aioredis
from aioredis import Redis
from fastapi import Depends

from swipe.settings import constants
from swipe.swipe_server.misc import dependencies
from swipe.swipe_server.misc.errors import SwipeError
from swipe.swipe_server.users.enums import Gender
from swipe.swipe_server.users.models import User, Location
from swipe.swipe_server.users.schemas import OnlineFilterBody, \
    UserCardPreviewOut
from swipe.ws_connection import PayloadEncoder

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


T = TypeVar('T')


class OnlineUserCache(ABC, Generic[T]):
    def __init__(self, redis: aioredis.Redis):
        self.redis = redis

    @abstractmethod
    async def get_online_users(
            self, age: int, filter_params: OnlineFilterBody) -> set[str]:
        pass

    @abstractmethod
    async def allowed_users(self) -> Optional[set[str]]:
        pass


@dataclass
class OnlineMatchmakingUserCacheParams:
    age: int
    gender: Optional[Gender] = None

    def cache_key(self) -> str:
        gender = self.gender or 'ALL'
        return f'matchmaking:{self.age}:{gender}'

    def online_keys(self):
        if not self.gender:
            raise SwipeError("gender must be set")

        result = [
            f'matchmaking:{self.age}:ALL',
        ]
        if self.gender != Gender.ATTACK_HELICOPTER:
            # attack helicopters go only to ALL gender cache
            result.extend([
                f'matchmaking:{self.age}:{self.gender}',
            ])
        return result


class RedisMatchmakingOnlineUserService(
    OnlineUserCache[OnlineMatchmakingUserCacheParams]):
    MATCHMAKING_ALL_USERS_KEY = 'matchmaking_all'

    def __init__(self,
                 redis: Redis = Depends(dependencies.redis)):
        super().__init__(redis)

    async def allowed_users(self) -> Optional[set[str]]:
        return await self.redis.smembers(f'{self.MATCHMAKING_ALL_USERS_KEY}')

    async def get_online_users(
            self, age: int, filter_params: OnlineFilterBody) -> set[str]:
        cache_params = OnlineMatchmakingUserCacheParams(
            age=age, gender=filter_params.gender)
        return await self.redis.smembers(cache_params.cache_key())

    async def add_to_online_caches(self, user: User):
        logger.info(f"Adding {user.id} to matchmaking cache sets")
        # add to all online sets
        cache_params = OnlineMatchmakingUserCacheParams(
            age=user.age,
            gender=user.gender
        )
        user_id = str(user.id)
        for key in cache_params.online_keys():
            await self.redis.sadd(key, user_id)

        await self.redis.sadd(f'{self.MATCHMAKING_ALL_USERS_KEY}', user_id)

    async def remove_from_online_caches(self, user: User):
        user_id = str(user.id)

        logger.info(f"Removing {user_id} from matchmaking user list")
        cache_params = OnlineMatchmakingUserCacheParams(
            age=user.age, gender=user.gender)
        # removing this user from all online caches
        for key in cache_params.online_keys():
            await self.redis.srem(key, user_id)
        await self.redis.srem(f'{self.MATCHMAKING_ALL_USERS_KEY}', user_id)


class RedisOnlineUserService(OnlineUserCache[OnlineUserCacheParams]):
    """
    Maintains two user caches: those who are currently online
    and those who have been online in the recent time.
    The second cache is used to remove users from the main cache after
    they have been offline for a certain time.
    """

    RECENTLY_ONLINE_KEY = 'recently_online_user'
    ONLINE_USER_KEY = 'online_user'
    USER_TOKEN_KEY = 'user_token'

    def __init__(self,
                 redis: Redis = Depends(dependencies.redis)):
        super().__init__(redis)

    async def allowed_users(self) -> Optional[set[str]]:
        return None

    async def get_online_users(
            self, age: int, filter_params: OnlineFilterBody) -> set[str]:
        cache_params = OnlineUserCacheParams(
            age=age, country=filter_params.country,
            city=filter_params.city, gender=filter_params.gender)
        return await self.redis.smembers(cache_params.cache_key())

    async def cache_user(self, user: User):
        json_data = UserCardPreviewOut.from_orm(user).json()
        # TODO man, I need a separate connection without decoding
        # but I don't wanna do that atm
        # json_data = zlib.compress(json_data.encode('utf-8'))

        await self.redis.set(f'{self.ONLINE_USER_KEY}:{user.id}', json_data)

    async def add_to_online_caches(self, user: User):
        logger.info(f"Adding {user.id} to online cache sets")
        # add to all online sets
        cache_params = OnlineUserCacheParams(
            age=user.age,
            country=user.location.country,
            city=user.location.city,
            gender=user.gender
        )
        user_id = str(user.id)
        for key in cache_params.online_keys():
            logger.debug(f"Adding {user_id} to {key}")
            await self.redis.sadd(key, user_id)

        await self.cache_user(user)

    async def remove_from_online_caches(
            self, user: User, location: Optional[Location] = None):
        logger.info(f"Removing {user.id} from online caches")
        country = location.country if location else user.location.country
        city = location.city if location else user.location.city
        cache_params = OnlineUserCacheParams(
            age=user.age, country=country, city=city, gender=user.gender)
        # removing this user from all online caches
        user_id = str(user.id)
        for key in cache_params.online_keys():
            logger.debug(f"Removing {user.id} from cache {key}")
            await self.redis.srem(key, user_id)

        logger.debug(f"Removing {user.id} from online user cache")
        await self.redis.delete(f'{self.ONLINE_USER_KEY}:{user.id}')

    async def invalidate_online_user_cache(self):
        for key in await self.redis.keys('online:*'):
            await self.redis.delete(key)

    async def update_recently_online_cache(
            self, recently_online_ttl=constants.RECENTLY_ONLINE_TTL_SEC):
        logger.info("Removing recently online users from the online cache")
        # Should be run periodically to remove users from the online cache
        for key in await self.redis.keys(f'{self.RECENTLY_ONLINE_KEY}:*'):
            user_data = await self.redis.get(key)
            user_data = json.loads(user_data)
            # dude's been gone for too long
            online_time_diff = (int(time.time()) - user_data['last_online'])
            if online_time_diff > recently_online_ttl:
                user_id = str(key).split(":")[1]

                logger.debug(f"Removing {user_id} from recently online users")
                # removing this dude from the recently_online list
                await self.redis.delete(key)

                cache_params = OnlineUserCacheParams(
                    age=user_data['age'], country=user_data['country'],
                    city=user_data['city'], gender=user_data['gender'])

                logger.info(f"Removing {user_id} from online caches")
                for online_key in cache_params.online_keys():
                    logger.debug(f"Removing {user_id} from {online_key}")
                    await self.redis.srem(online_key, user_id)

    async def add_to_recently_online_cache(self, user: User):
        user_id = str(user.id)

        last_online = datetime.utcnow()
        user_data = {
            # I'm intentionally not using last_online field from user object
            'last_online': int(last_online.timestamp()),
            'age': user.age,
            'country': user.location.country,
            'city': user.location.city,
            'gender': user.gender.value
        }
        # user_data = zlib.compress(json.dumps(user_data).encode('utf-8'))
        await self.redis.set(
            f'{self.RECENTLY_ONLINE_KEY}:{user_id}', json.dumps(user_data))

        # update last_online field here so that we could sort these entities
        # without touching the cache again
        last_online = last_online.isoformat()
        logger.debug(f"Updating {last_online=} field on online user {user_id}")
        cached_user = await self.redis.get(f'{self.ONLINE_USER_KEY}:{user_id}')

        if not cached_user:
            logger.debug(f"{user_id} not in online cache, saving")
            cached_user = UserCardPreviewOut.from_orm(user).dict()
        else:
            cached_user = json.loads(cached_user)

        cached_user['last_online'] = last_online
        # TODO stupid dump shit, use orjson
        await self.redis.set(f'{self.ONLINE_USER_KEY}:{user_id}',
                             json.dumps(cached_user, cls=PayloadEncoder))

    async def remove_from_recently_online(self, user_id: str):
        logger.debug(f"Removing {user_id} from recently online set")
        await self.redis.delete(f'{self.RECENTLY_ONLINE_KEY}:{user_id}')

    async def get_user_card_previews(self, user_ids: Iterable[str]) \
            -> Iterable[str]:
        return await self.redis.mget([
            f'{self.ONLINE_USER_KEY}:{user_id}' for user_id in user_ids
        ])

    async def get_user_card_preview_one(self, user_id: str) -> Optional[str]:
        return await self.redis.get(f'{self.ONLINE_USER_KEY}:{user_id}')

    async def is_online(self, user_id: str) -> Optional[str]:
        return await self.get_user_card_preview_one(user_id) is not None

    async def get_online_user_token(self, user_id: str) -> Optional[str]:
        logger.debug(f"Fetching auth token of {user_id} from cache")
        return await self.redis.get(f'{self.USER_TOKEN_KEY}:{user_id}')

    async def save_auth_token(self, user_id: str, token: str):
        logger.debug(f"Saving auth token of {user_id} to cache")
        await self.redis.setex(
            f'{self.USER_TOKEN_KEY}:{user_id}',
            time=constants.USER_AUTH_TOKEN_TTL_SEC, value=token)
