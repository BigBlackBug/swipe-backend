import uuid

import aioredis
import pytest
from httpx import AsyncClient
from pytest_mock import MockerFixture
from sqlalchemy.orm import Session

from swipe.swipe_server.misc.randomizer import RandomEntityGenerator
from swipe.swipe_server.users import swipe_bg_tasks
from swipe.swipe_server.users.models import User
from swipe.swipe_server.users.schemas import OnlineFilterBody, \
    PopularFilterBody, UserUpdate, LocationSchema
from swipe.swipe_server.users.services.online_cache import \
    RedisOnlineUserService, OnlineUserCacheParams
from swipe.swipe_server.users.services.redis_services import \
    RedisLocationService, RedisPopularService
from swipe.swipe_server.users.services.services import UserService, \
    PopularUserService


@pytest.mark.anyio
async def test_update_caches_after_location_update(
        randomizer: RandomEntityGenerator,
        client: AsyncClient,
        default_user: User,
        user_service: UserService,
        session: Session,
        fake_redis: aioredis.Redis,
        mocker: MockerFixture,
        redis_online: RedisOnlineUserService,
        redis_location: RedisLocationService,
        redis_popular: RedisPopularService,
):
    user_service.update_user(
        default_user, UserUpdate(location=LocationSchema(
            country='What Country',
            city='Hello',
            flag='f'
        )))

    await redis_online.add_to_online_caches(default_user)

    popular_service = PopularUserService(session, fake_redis)
    await popular_service.populate_popular_cache()

    # assuming some other users are in the cache for Hello
    cached_user_id = str(uuid.uuid4())
    filter_body_full = OnlineFilterBody(
        country='What Country',
        city='Hello',
        gender=default_user.gender
    )
    cache_settings_full = OnlineUserCacheParams(
        age=default_user.age,
        country='What Country',
        city='Hello',
        gender=default_user.gender
    )
    for key in cache_settings_full.online_keys():
        await redis_online.redis.sadd(key, cached_user_id)

    previous_location = default_user.location
    # old dude is in cache of his previous location
    old_location_cache_settings = OnlineUserCacheParams(
        age=default_user.age,
        country=previous_location.country,
        city=previous_location.city,
        gender=default_user.gender
    )
    for key in old_location_cache_settings.online_keys():
        await redis_online.redis.sadd(key, str(default_user.id))

    #     ---------------------------------------------
    from swipe.swipe_server.misc import dependencies
    def _redis():
        return fake_redis

    mocker.patch.object(dependencies, "redis", _redis)

    await swipe_bg_tasks.update_location_caches(default_user, previous_location)
    # assert country is saved to cache
    country_keys = await redis_location.redis.keys("country:*")
    assert 'country:What Country' in country_keys
    cities = await redis_location.redis.smembers('country:What Country')
    assert 'Hello' in cities

    # user is added to current caches
    assert await redis_online.get_online_users(
        default_user.age, filter_body_full) == {
               str(default_user.id), cached_user_id}
    cache_settings_country = OnlineFilterBody(
        country='What Country',
        gender=default_user.gender
    )
    assert await redis_online.get_online_users(
        default_user.age, cache_settings_country) == {
               str(default_user.id), cached_user_id}

    assert await redis_popular.get_popular_user_ids(PopularFilterBody(
        gender=default_user.gender,
        city='Hello',
        country='What Country'
    )) == [str(default_user.id)]

    assert await redis_popular.get_popular_user_ids(PopularFilterBody(
        gender=default_user.gender,
        country='What Country'
    )) == [str(default_user.id)]

    assert await redis_popular.get_popular_user_ids(PopularFilterBody(
        gender=default_user.gender
    )) == [str(default_user.id)]

    assert await redis_popular.get_popular_user_ids(PopularFilterBody()) \
           == [str(default_user.id)]

    # user is removed from old cache
    assert await redis_online.get_online_users(old_location_cache_settings) \
           == set()

    assert await redis_popular.get_popular_user_ids(PopularFilterBody(
        gender=default_user.gender,
        city=previous_location.city,
        country=previous_location.country
    )) == []

    assert await redis_popular.get_popular_user_ids(PopularFilterBody(
        gender=default_user.gender,
        country=previous_location.country
    )) == []
