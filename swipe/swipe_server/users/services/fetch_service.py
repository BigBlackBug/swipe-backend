import logging
from dataclasses import dataclass

from aioredis import Redis
from fastapi import Depends

from swipe.settings import settings
from swipe.swipe_server.misc import dependencies
from swipe.swipe_server.users.services.online_cache import OnlineUserCache
from swipe.swipe_server.users.services.redis_services import RedisUserFetchService, \
    RedisPopularService, RedisBlacklistService, UserFetchCacheKey
from swipe.swipe_server.users.schemas import OnlineFilterBody

logger = logging.getLogger(__name__)


@dataclass
class UserPool:
    online_users: list[str]
    head: int = 0


class FetchUserService:
    def __init__(self,
                 online_cache: OnlineUserCache,
                 redis: Redis = Depends(dependencies.redis)):
        self.redis_fetch = RedisUserFetchService(redis)
        self.redis_popular = RedisPopularService(redis)
        self.redis_online = online_cache
        self.redis_blacklist = RedisBlacklistService(redis)

    async def collect(self, user_id: str, user_age: int,
                      filter_params: OnlineFilterBody,
                      disallowed_users: set[str] = None) -> set[str]:
        logger.info(f"Collecting users for {user_id}, params: {filter_params}")
        # TODO save current age diff with session ID
        # so that we don't go through all previous age ranges
        # every time
        disallowed_users = disallowed_users or set()
        disallowed_users.add(user_id)

        # checking against currently online users
        allowed_users = await self.redis_online.allowed_users()
        logger.info(f"Allowed users: {allowed_users}")
        logger.info(f"Disallowed users: {disallowed_users}")

        fetch_cache_params = UserFetchCacheKey(
            session_id=filter_params.session_id,
            user_id=user_id
        )

        await self.redis_fetch.drop_obsolete_caches(fetch_cache_params)
        cached_user_ids: set[str] = \
            await self.redis_fetch.get_response_cache(fetch_cache_params)

        age_difference = settings.ONLINE_USER_DEFAULT_AGE_DIFF

        logger.info(f"Got filter params {filter_params}, "
                    f"previous cache {cached_user_ids}")

        # premium filtered by gender
        # premium filtered by location(whole country/my city)
        # Russia, SPB, 25+-2,3,4, ALL

        # age->(index,user_list)
        online_users_pool = {}

        result = set()
        while len(result) < filter_params.limit \
                and age_difference <= settings.ONLINE_USER_MAX_AGE_DIFF:
            shift = -1
            # we're going age+0,-1,1,-2,2 etc
            sorted_age_range = [user_age]
            logger.info(f"Current age {user_age}, diff {age_difference}")
            while len(sorted_age_range) < age_difference * 2 + 1:
                sorted_age_range.append(user_age + shift)
                sorted_age_range.append(user_age - shift)
                shift = - (abs(shift) + 1)
            logger.info(f"Checking age range {sorted_age_range}")

            # filling current user pool
            for current_age in sorted_age_range:
                if current_age not in online_users_pool:
                    user_cache = \
                        await self.redis_online.get_online_users(
                            current_age, filter_params)
                    user_cache = list(user_cache)
                    online_users_pool[current_age] = UserPool(user_cache)
                    logger.info(f"Got {len(user_cache)} online users "
                                f"for age={current_age}")

            for current_age in sorted_age_range:
                current_pool: UserPool = online_users_pool[current_age]
                # getting one user per age pool
                if current_pool.head < len(current_pool.online_users):
                    candidate = current_pool.online_users[current_pool.head]
                    current_pool.head += 1
                    logger.info(f"Testing candidate {candidate} for {user_id}")
                    if candidate not in cached_user_ids \
                            and candidate not in disallowed_users:
                        if allowed_users is None or \
                                allowed_users and candidate in allowed_users:
                            logger.info(
                                f"Found {candidate} in user pool "
                                f"for age={current_age}")
                            result.add(candidate)
                        else:
                            logger.info(
                                f"{candidate} is disallowed for {user_id}")

                if len(result) == filter_params.limit:
                    # got enough users
                    break
            else:
                # online users depleted, extend age_diff and try again
                age_difference += settings.ONLINE_USER_AGE_DIFF_STEP
                logger.info(
                    f"Online users depleted for range {sorted_age_range}, "
                    f"increasing age_difference to {age_difference}")
                continue

        # got enough users or max age diff reached
        logger.info(f"Adding {result} to user request cache "
                    f"for {fetch_cache_params.cache_key()}")
        # adding currently returned users to cache
        await self.redis_fetch.add_to_response_cache(
            fetch_cache_params, result)
        return result
