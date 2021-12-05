import datetime

import pytest
from aioredis import Redis
from httpx import AsyncClient, Response
from sqlalchemy.orm import Session

from swipe.settings import settings, constants
from swipe.swipe_server.users import models
from swipe.swipe_server.users.redis_services import RedisSwipeReaperService


@pytest.mark.anyio
async def test_free_swipes_can_be_reaped(
        client: AsyncClient,
        session: Session,
        fake_redis: Redis,
        default_user: models.User,
        default_user_auth_headers: dict[str, str]):
    """
    Test must succeed when there is no key
    """
    old_swipes = default_user.swipes
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/me/swipes/reap",
        headers=default_user_auth_headers
    )
    session.refresh(default_user)
    assert response.status_code == 200
    assert default_user.swipes == \
           old_swipes + constants.SWIPES_PER_TIME_PERIOD
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
    await redis_swipes.reset_swipe_reap_timestamp(default_user.id)
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/me/swipes/reap",
        headers=default_user_auth_headers
    )
    assert response.status_code == 409


@pytest.mark.anyio
async def test_free_swipes_status_can_be_reaped(
        client: AsyncClient, fake_redis: Redis,
        default_user: models.User,
        redis_swipes: RedisSwipeReaperService,
        default_user_auth_headers: dict[str, str]):
    # no key present -> okay, swipes can be reaped
    response: Response = await client.get(
        f"{settings.API_V1_PREFIX}/me/swipes/status",
        headers=default_user_auth_headers
    )
    assert response.status_code == 200
    assert response.json()['reap_timestamp'] is None


@pytest.mark.anyio
async def test_free_swipes_status_can_not_be_reaped(
        client: AsyncClient, fake_redis: Redis,
        default_user: models.User,
        redis_swipes: RedisSwipeReaperService,
        default_user_auth_headers: dict[str, str]):
    # key exists in the future -> not okay
    reap_date: datetime = \
        await redis_swipes.reset_swipe_reap_timestamp(default_user.id)
    reap_date = reap_date.isoformat()

    response: Response = await client.get(
        f"{settings.API_V1_PREFIX}/me/swipes/status",
        headers=default_user_auth_headers
    )
    assert response.status_code == 200
    assert response.json()['reap_timestamp'] == reap_date


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


# @pytest.mark.anyio
# async def test_add_swipes(
#         client: AsyncClient,
#         default_user: models.User,
#         default_user_auth_headers: dict[str, str]):
#     swipes_before = default_user.swipes
#     swipes_added = 10
#
#     response: Response = await client.post(
#         f"{settings.API_V1_PREFIX}/me/swipes",
#         json={
#             'swipes': swipes_added,
#             'reason': 'whatever'
#         },
#         headers=default_user_auth_headers
#     )
#     assert response.status_code == 201
#     assert default_user.swipes == swipes_before + swipes_added
