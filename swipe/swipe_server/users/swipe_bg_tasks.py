import logging

from swipe.swipe_server.misc import dependencies
from swipe.swipe_server.users.models import User, Location
from swipe.swipe_server.users.redis_services import RedisLocationService, \
    RedisOnlineUserService
from swipe.swipe_server.users.services import PopularUserService

logger = logging.getLogger(__name__)


async def update_location_caches(user: User, old_location: Location):
    with dependencies.db_context() as db:
        redis_online = RedisOnlineUserService(dependencies.redis())
        popular_service = PopularUserService(db, dependencies.redis())
        redis_location = RedisLocationService(dependencies.redis())
        await redis_location.add_cities(
            user.location.country, [user.location.city])

        try:
            await redis_online.remove_from_online_caches(
                user, old_location)
            # putting him back to caches with correct location
            await redis_online.add_to_online_caches(user)
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
