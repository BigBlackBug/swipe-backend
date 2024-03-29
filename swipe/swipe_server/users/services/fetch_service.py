import logging
from dataclasses import dataclass

from aioredis import Redis
from fastapi import Depends

from swipe.settings import settings
from swipe.swipe_server.misc import dependencies
from swipe.swipe_server.users.schemas import OnlineFilterBody
from swipe.swipe_server.users.services.online_cache import OnlineUserCache
from swipe.swipe_server.users.services.redis_services import \
    RedisUserFetchService, \
    RedisPopularService, RedisBlacklistService, UserFetchCacheKey

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
        disallowed_users = disallowed_users or set()
        disallowed_users.add(user_id)

        # checking against currently online users
        allowed_users = await self.redis_online.allowed_users()
        logger.info(f"Allowed users: {allowed_users or 'ALL'}")
        logger.info(f"Disallowed users: {disallowed_users}")

        fetch_cache_params = UserFetchCacheKey(
            session_id=filter_params.session_id,
            user_id=user_id
        )

        await self.redis_fetch.drop_obsolete_caches(fetch_cache_params)
        cached_user_ids: set[str] = \
            await self.redis_fetch.get_response_cache(fetch_cache_params)

        age_difference = \
            await self.redis_fetch.get_cached_age_difference(
                fetch_cache_params)
        logger.debug(f"Cached age difference {age_difference}")
        # age->(index, user_list)
        online_users_pool = {}

        result = set()
        while len(result) < filter_params.limit \
                and age_difference <= settings.USER_FETCH_MAX_AGE_DIFF:
            shift = -1
            # we're going age+0,-1,1,-2,2 etc
            sorted_age_range = [user_age]
            logger.debug(f"Current age {user_age}, diff {age_difference}")
            while len(sorted_age_range) < age_difference * 2 + 1:
                # less than user_age so we're checking it here
                potential_age = user_age + shift
                if potential_age >= settings.USER_FETCH_MINIMUM_AGE:
                    sorted_age_range.append(potential_age)

                sorted_age_range.append(user_age - shift)
                shift = - (abs(shift) + 1)
            logger.debug(f"Checking age range {sorted_age_range}")

            # filling current user pool
            for current_age in sorted_age_range:
                if current_age not in online_users_pool:
                    user_cache = \
                        await self.redis_online.get_online_users(
                            current_age, filter_params)
                    user_cache = list(user_cache)
                    online_users_pool[current_age] = UserPool(user_cache)
                    logger.debug(f"Got {len(user_cache)} online users "
                                 f"for age={current_age}")

            for current_age in sorted_age_range:
                current_pool: UserPool = online_users_pool[current_age]
                # getting one user per age pool
                if current_pool.head < len(current_pool.online_users):
                    candidate = current_pool.online_users[current_pool.head]
                    current_pool.head += 1
                    logger.debug(f"Testing candidate {candidate} for {user_id}")
                    if candidate not in cached_user_ids \
                            and candidate not in disallowed_users:
                        if allowed_users is None or \
                                allowed_users and candidate in allowed_users:
                            logger.info(
                                f"Found {candidate} in user pool "
                                f"for age={current_age}")
                            result.add(candidate)
                        else:
                            logger.debug(
                                f"{candidate} is disallowed for {user_id}")

                if len(result) == filter_params.limit:
                    # got enough users
                    break
            else:
                # online users depleted, extend age_diff and try again
                age_difference += settings.USER_FETCH_AGE_DIFF_STEP
                logger.debug(
                    f"Online users depleted for range {sorted_age_range}, "
                    f"increasing age_difference to {age_difference}")
                continue

        # got enough users or max age diff reached
        await self.redis_fetch.add_to_response_cache(
            fetch_cache_params, result)

        await self.redis_fetch.save_age_difference_cache(
            fetch_cache_params, age_difference)
        return result
