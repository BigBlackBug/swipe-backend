import datetime
import logging

from sqlalchemy import select

from swipe.settings import constants
from swipe.swipe_server.misc import dependencies
from swipe.swipe_server.users.models import User, Location
from swipe.swipe_server.users.services.online_cache import \
    RedisOnlineUserService
from swipe.swipe_server.users.services.popular_cache import PopularUserService, \
    CountryCacheService
from swipe.swipe_server.users.services.redis_services import \
    RedisLocationService, RedisUserCacheService, RedisUserFetchService

logger = logging.getLogger(__name__)


async def update_location_caches(user: User, old_location: Location):
    with dependencies.db_context() as db:
        redis = dependencies.redis()
        redis_online = RedisOnlineUserService(redis)
        popular_service = PopularUserService(db, redis)
        redis_location = RedisLocationService(redis)
        redis_user = RedisUserCacheService(redis)
        await redis_location.add_cities(
            user.location.country, [user.location.city])

        try:
            await redis_online.remove_from_online_caches(
                user, old_location)
            # putting him back to caches with correct location
            await redis_online.add_to_online_caches(user)
            await redis_user.cache_user(user)
        except:
            logger.exception(f"Unable to update caches for {user.id}"
                             f"after location update")

        logger.info("Updating global popular cache")
        await popular_service.populate_cache()
        await popular_service.populate_cache(gender=user.gender)

        logger.info(
            f"Updating gender: {user.gender}, "
            f"previous location: '{old_location}', "
            f"current location: '{user.location}' "
            f"popular cache")
        await popular_service.populate_cache(
            gender=user.gender,
            country=old_location.country)
        await popular_service.populate_cache(
            gender=user.gender,
            country=user.location.country)

        await popular_service.populate_cache(
            gender=user.gender,
            country=old_location.country,
            city=old_location.city)
        await popular_service.populate_cache(
            gender=user.gender,
            country=user.location.country,
            city=user.location.city)


# TODO just for devs
async def populate_online_caches():
    redis_online = RedisOnlineUserService(dependencies.redis())
    redis_fetch = RedisUserFetchService(dependencies.redis())
    logger.info("Invalidating online response cache")
    await redis_fetch.drop_all_response_caches()
    # TODO just for tests, because chat server is also being restarted
    logger.info("Invalidating online user cache")
    await redis_online.invalidate_online_user_cache()

    with dependencies.db_context() as db:
        last_online = \
            datetime.datetime.utcnow() - \
            datetime.timedelta(seconds=constants.RECENTLY_ONLINE_TTL_SEC)
        last_online_users = \
            db.execute(select(User).where(
                (User.deactivation_date == None) &
                (User.last_online > last_online) &
                (User.last_online != None)  # noqa
            )).scalars().all()
        logger.info(f"Found {len(last_online_users)} "
                    f"online users during previous "
                    f"{constants.RECENTLY_ONLINE_TTL_SEC} secs")
        for user in last_online_users:
            logger.debug(f"Adding {user.id} to recently online set")
            await redis_online.add_to_recently_online_cache(user)
            logger.debug(f"Adding {user.id} to online set")
            await redis_online.add_to_online_caches(user)


# TODO just for dev
async def drop_user_cache():
    redis_user = RedisUserCacheService(dependencies.redis())
    await redis_user.drop_cache()


async def populate_country_cache():
    logger.info("Populating country cache")
    with dependencies.db_context() as db:
        cache_service = CountryCacheService(db, dependencies.redis())
        await cache_service.populate_country_cache()


async def populate_popular_cache():
    logger.info("Starting popular cache populating job")
    with dependencies.db_context() as db:
        redis_popular = PopularUserService(db, dependencies.redis())
        await redis_popular.populate_popular_cache()


async def update_recently_online_cache():
    logger.info("Staring recently online cache updating job")
    redis_online = RedisOnlineUserService(dependencies.redis())
    await redis_online.update_recently_online_cache()
