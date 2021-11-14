import pytest
from aioredis import Redis
from httpx import AsyncClient, Response
from sqlalchemy.orm import Session

from swipe.settings import settings, constants
from swipe.swipe_server.users import models


@pytest.mark.anyio
async def test_auth_new_user(client: AsyncClient,
                             fake_redis: Redis) -> None:
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/auth", json={
            'auth_provider': 'google',
            'provider_user_id': 'superid'
        }
    )
    assert response.status_code == 201
    assert response.json().get('access_token')
    assert response.json().get('user_id')

    # free swipes cache is set
    user_id = response.json().get('user_id')
    assert await fake_redis.get(
        f'{constants.FREE_SWIPES_REDIS_PREFIX}{user_id}')


@pytest.mark.anyio
async def test_auth_existing_user(client: AsyncClient,
                                  session: Session,
                                  fake_redis: Redis,
                                  default_user: models.User) -> None:
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/auth", json={
            'auth_provider': default_user.auth_info.auth_provider,
            'provider_user_id': default_user.auth_info.provider_user_id
        }
    )
    assert response.status_code == 200
    assert response.json().get('access_token') \
           == default_user.auth_info.access_token
    assert response.json().get('user_id')

    # free swipes cache is set
    user_id = response.json().get('user_id')
    assert await fake_redis.get(
        f'{constants.FREE_SWIPES_REDIS_PREFIX}{user_id}')
