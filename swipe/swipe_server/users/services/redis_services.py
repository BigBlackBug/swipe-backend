import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Tuple, AsyncGenerator, Iterable
from uuid import UUID

import aioredis
from aioredis import Redis
from fastapi import Depends

from swipe.settings import settings, constants
from swipe.swipe_server.misc import dependencies
from swipe.swipe_server.users.enums import Gender
from swipe.swipe_server.users.models import User
from swipe.swipe_server.users.schemas import PopularFilterBody, \
    UserCardPreviewOut
from swipe.swipe_server.utils import enable_blacklist

logger = logging.getLogger(__name__)


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
        logger.info(f"Adding {blocked_user_id} to {blocked_by_id} blacklist")
        await self.redis.sadd(f'{self.BLACKLIST_KEY}:{blocked_by_id}',
                              blocked_user_id)

        logger.info(f"Adding {blocked_by_id} to {blocked_user_id} blacklist")
        await self.redis.sadd(
            f'{self.BLACKLIST_KEY}:{blocked_user_id}', blocked_by_id)

    @enable_blacklist()
    async def populate_blacklist(self, user_id: str, blacklist: set[str]):
        logger.info(f"Populating blacklist cache for {user_id}: {blacklist}")
        if not blacklist:
            return
        await self.redis.sadd(f'{self.BLACKLIST_KEY}:{user_id}', *blacklist)

    @enable_blacklist()
    async def drop_blacklist_cache(self, user_id: str):
        logger.info(f"Dropping blacklist cache for {user_id}")
        await self.redis.delete(f'{self.BLACKLIST_KEY}:{user_id}')


class RedisChatCacheService:
    """
    Chat cache keeps user's chats for the purpose of speeding up
    matchmaker queries. We shouldn't offer users who already have chats
    with each other
    """
    CHAT_CACHE_KEY = 'chat_cache'

    def __init__(self,
                 redis: Redis = Depends(dependencies.redis)):
        self.redis = redis

    async def drop_chat_partner_cache(self, user_id: str):
        logger.info(f"Dropping chat cache of {user_id}")
        await self.redis.delete(f'{self.CHAT_CACHE_KEY}:{user_id}')

    async def add_chat_partner(self, creator_id: str, target_id: str):
        logger.info(f"Adding chat partner {creator_id} to {target_id} cache")
        await self.redis.sadd(f'{self.CHAT_CACHE_KEY}:{target_id}', creator_id)

    async def save_chat_partner_cache(self, user_id: str,
                                      partner_ids: list[str]):
        await self.redis.delete(f'{self.CHAT_CACHE_KEY}:{user_id}')
        if partner_ids:
            logger.info(f"Saving chat partners of {user_id}, {partner_ids}")
            await self.redis.sadd(
                f'{self.CHAT_CACHE_KEY}:{user_id}', *partner_ids)

    async def get_chat_partners(self, user_id) -> set[str]:
        return await self.redis.smembers(f'{self.CHAT_CACHE_KEY}:{user_id}')


FETCH_REQUEST_KEY = 'fetch_request'


@dataclass
class UserFetchCacheKey:
    user_id: str
    session_id: str

    def cache_key(self):
        return f'{FETCH_REQUEST_KEY}:{self.user_id}:{self.session_id}'

    def key_user_wildcard(self):
        return f'{FETCH_REQUEST_KEY}:{self.user_id}:*'


class RedisUserFetchService:
    """
    Caches responses for /fetch endpoint for each user
    """

    def __init__(self,
                 redis: Redis = Depends(dependencies.redis)):
        self.redis = redis

    async def get_response_cache(
            self, cache_settings: UserFetchCacheKey) \
            -> set[str]:
        if await self.redis.exists(cache_settings.cache_key()):
            return await self.redis.smembers(cache_settings.cache_key())

        return set()

    async def drop_obsolete_caches(
            self, cache_settings: UserFetchCacheKey):
        if not await self.redis.exists(cache_settings.cache_key()):
            # no key with current session
            # but there is an older one
            if await self.redis.keys(cache_settings.key_user_wildcard()):
                logger.info(
                    f"Removing previous cache for {cache_settings.user_id}")
                # drop other requests for other session_ids
                await self.drop_response_cache(cache_settings.user_id)

    async def add_to_response_cache(
            self, cache_settings: UserFetchCacheKey,
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


class RedisFirebaseService:
    FIREBASE_KEY = 'firebase_tokens'
    FIREBASE_COOLDOWN_KEY = 'firebase_cooldown'

    def __init__(self,
                 redis: aioredis.Redis = Depends(dependencies.redis)):
        self.redis = redis

    async def get_firebase_token(self, user_id: str):
        return await self.redis.hget(self.FIREBASE_KEY, user_id)

    async def remove_token_from_cache(self, user_id: str):
        await self.redis.hdel(self.FIREBASE_KEY, user_id)

    async def add_token_to_cache(self, user_id: str, token: str):
        if not token:
            return
        await self.redis.hset(self.FIREBASE_KEY, user_id, token)

    async def is_on_cooldown(self, sender_id: str, recipient_id: str) -> bool:
        return await self.redis.get(
            f'{self.FIREBASE_COOLDOWN_KEY}:{sender_id}:{recipient_id}')

    async def set_cooldown_token(self,  sender_id: str, recipient_id: str):
        await self.redis.setex(
            f'{self.FIREBASE_COOLDOWN_KEY}:{sender_id}:{recipient_id}',
            time=constants.FIREBASE_NOTIFICATION_COOLDOWN_SEC,
            value='1')
