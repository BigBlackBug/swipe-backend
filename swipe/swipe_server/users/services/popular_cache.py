import logging
from typing import Optional

import aioredis
from fastapi import Depends
from sqlalchemy.orm import Session

from swipe.swipe_server.misc import dependencies
from swipe.swipe_server.users.enums import Gender
from swipe.swipe_server.users.models import User
from swipe.swipe_server.users.services.redis_services import \
    RedisPopularService, RedisLocationService
from swipe.swipe_server.users.services.user_service import UserService

logger = logging.getLogger(__name__)


class PopularUserService:
    def __init__(self, db: Session = Depends(dependencies.db),
                 redis: aioredis.Redis = Depends(dependencies.redis)):
        self.user_service = UserService(db)
        self.redis_popular = RedisPopularService(redis)
        self.redis_locations = RedisLocationService(redis)

    async def populate_cache(self, country: Optional[str] = None,
                             city: Optional[str] = None,
                             gender: Optional[Gender] = None):
        users: list[User] = self.user_service.fetch_popular(
            country=country, city=city, gender=gender)
        logger.info(
            f"Got {len(users)} popular users from db for: "
            f"country:{country or 'ALL'}, city:{city or 'ALL'}, "
            f"gender:{gender or 'ALL'}")
        await self.redis_popular.save_popular_users(
            country=country, city=city, gender=gender, users=users)

    async def populate_popular_cache(self):
        logger.info("Populating popular cache")
        locations = self.redis_locations.fetch_locations()

        # global popular cache
        logger.info("Populating global cache")
        await self.populate_cache(gender=Gender.MALE)
        await self.populate_cache(gender=Gender.FEMALE)
        await self.populate_cache()

        async for country, cities in locations:
            logger.info(f"Populating cache for country: '{country}'")
            await self.populate_cache(country=country, gender=Gender.MALE)
            await self.populate_cache(country=country, gender=Gender.FEMALE)
            await self.populate_cache(country=country)

            logger.info(f"Populating cities cache for '{country}', "
                        f"cities: '{cities}'")
            for city in cities:
                await self.populate_cache(
                    country=country, city=city, gender=Gender.MALE)
                await self.populate_cache(
                    country=country, city=city, gender=Gender.FEMALE)
                await self.populate_cache(country=country, city=city)


class CountryCacheService:
    def __init__(self, db: Session, redis: aioredis.Redis):
        self.user_service = UserService(db)
        self.redis_popular = RedisPopularService(redis)
        self.redis_locations = RedisLocationService(redis)

    async def populate_country_cache(self):
        locations: dict[str, list[str]] = self.user_service.fetch_locations()

        logger.info("Dropping country cache")
        await self.redis_locations.drop_country_cache()

        logger.info(
            f"Populating location cache with locations: {locations}")
        for country, cities in locations.items():
            logger.info(f"Saving {cities} to {country}")
            await self.redis_locations.add_cities(country, cities)
