import datetime
import time

import pytest
from aioredis import Redis
from httpx import AsyncClient, Response

from settings import constants, settings
from swipe.users import models


@pytest.mark.anyio
async def test_free_swipes_can_be_reaped(
        client: AsyncClient, fake_redis: Redis,
        default_user: models.User,
        default_user_auth_headers: dict[str, str]):
    """
    Test must succeed when the reap time is behind current time
    """
    time_in_the_past = datetime.datetime.now() - datetime.timedelta(hours=1)
    reap_key = f'{constants.FREE_SWIPES_REDIS_PREFIX}{default_user.id}'
    await fake_redis.set(reap_key, int(time_in_the_past.timestamp()))

    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/me/swipes/reap",
        headers=default_user_auth_headers
    )
    assert response.status_code == 200
    assert response.json()['swipes'] == default_user.swipes
    assert response.json()['reap_timestamp'] > time.time()

    assert int(await fake_redis.get(reap_key)) \
           == response.json()['reap_timestamp']


@pytest.mark.anyio
async def test_free_swipes_can_not_be_reaped(
        client: AsyncClient, fake_redis: Redis,
        default_user: models.User,
        default_user_auth_headers: dict[str, str]):
    """
    Test must succeed when the reap time is ahead of current time
    """
    time_in_the_future = datetime.datetime.now() + datetime.timedelta(hours=1)
    reap_key = f'{constants.FREE_SWIPES_REDIS_PREFIX}{default_user.id}'
    await fake_redis.set(reap_key, int(time_in_the_future.timestamp()))

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
    time_in_the_past = datetime.datetime.now() - datetime.timedelta(hours=1)
    reap_key = f'{constants.FREE_SWIPES_REDIS_PREFIX}{default_user.id}'
    await fake_redis.set(reap_key, int(time_in_the_past.timestamp()))

    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/me/swipes/reap",
        headers=default_user_auth_headers
    )
    assert response.status_code == 200
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/me/swipes/reap", json={
            'auth_provider': default_user.auth_info.auth_provider,
            'provider_token': default_user.auth_info.provider_token,
            'provider_user_id': default_user.auth_info.provider_user_id
        }, headers=default_user_auth_headers
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
            'swipe_number': swipes_added,
            'reason': 'whatever'
        },
        headers=default_user_auth_headers
    )
    assert response.status_code == 201
    assert default_user.swipes == swipes_before + swipes_added
