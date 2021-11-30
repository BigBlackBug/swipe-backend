import datetime

import pytest
from aioredis import Redis
from httpx import AsyncClient, Response

from swipe.settings import settings
from swipe.swipe_server.users import models
from swipe.swipe_server.users.redis_services import RedisSwipeReaperService


@pytest.mark.anyio
async def test_free_swipes_can_be_reaped(
        client: AsyncClient, fake_redis: Redis,
        default_user: models.User,
        default_user_auth_headers: dict[str, str]):
    """
    Test must succeed when there is no key
    """
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/me/swipes/reap",
        headers=default_user_auth_headers
    )
    assert response.status_code == 200
    assert response.json()['swipes'] == default_user.swipes


@pytest.mark.anyio
async def test_free_swipes_can_not_be_reaped(
        client: AsyncClient, fake_redis: Redis,
        default_user: models.User,
        redis_swipes: RedisSwipeReaperService,
        default_user_auth_headers: dict[str, str]):
    """
    Test must succeed when the reap time is ahead of current time
    """
    time_in_the_future = datetime.datetime.now() + datetime.timedelta(hours=1)
    time_in_the_future = int(time_in_the_future.timestamp())
    await redis_swipes.reset_swipe_reap_timestamp(
        default_user.id, time_in_the_future)
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/me/swipes/reap",
        headers=default_user_auth_headers
    )
    assert response.status_code == 409


@pytest.mark.anyio
async def test_disallow_double_reaping(
        client: AsyncClient, fake_redis: Redis,
        default_user: models.User,
        default_user_auth_headers: dict[str, str]):
    """
    Test must succeed when the second reap call fails
    """
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/me/swipes/reap",
        headers=default_user_auth_headers
    )
    assert response.status_code == 200
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/me/swipes/reap",
        headers=default_user_auth_headers
    )
    assert response.status_code == 409


@pytest.mark.anyio
async def test_add_swipes(
        client: AsyncClient,
        default_user: models.User,
        default_user_auth_headers: dict[str, str]):
    """
    Test must succeed when the user's number of swipes changes
    """
    swipes_before = default_user.swipes
    swipes_added = 10

    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/me/swipes",
        json={
            'swipes': swipes_added,
            'reason': 'whatever'
        },
        headers=default_user_auth_headers
    )
    assert response.status_code == 201
    assert default_user.swipes == swipes_before + swipes_added
