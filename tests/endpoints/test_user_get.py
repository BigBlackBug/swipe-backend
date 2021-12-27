import datetime

import aioredis
import pytest
from httpx import AsyncClient, Response
from sqlalchemy.orm import Session

from swipe.settings import settings
from swipe.swipe_server.misc.randomizer import RandomEntityGenerator
from swipe.swipe_server.users.models import User
from swipe.swipe_server.users.services.online_cache import \
    RedisOnlineUserService
from swipe.swipe_server.users.services.redis_services import \
    RedisUserCacheService
from swipe.swipe_server.users.services.user_service import UserService


@pytest.mark.anyio
async def test_user_get_online(
        client: AsyncClient,
        default_user: User,
        session: Session,
        user_service: UserService,
        fake_redis: aioredis.Redis,
        randomizer: RandomEntityGenerator,
        redis_online: RedisOnlineUserService,
        default_user_auth_headers: dict[str, str]):
    default_user.date_of_birth = datetime.date.today().replace(year=1998)

    # --------------------------------------------------------------------------
    user_1 = randomizer.generate_random_user()
    user_1.last_online = None
    session.commit()
    # --------------------------------------------------------------------------

    response: Response = await client.get(
        f"{settings.API_V1_PREFIX}/users/{user_1.id}",
        headers=default_user_auth_headers
    )
    assert response.status_code == 200
    resp_data = response.json()
    assert resp_data['online']


@pytest.mark.anyio
async def test_user_get_offline(
        client: AsyncClient,
        default_user: User,
        session: Session,
        user_service: UserService,
        fake_redis: aioredis.Redis,
        randomizer: RandomEntityGenerator,
        redis_online: RedisOnlineUserService,
        default_user_auth_headers: dict[str, str]):
    default_user.date_of_birth = datetime.date.today().replace(year=1998)

    # --------------------------------------------------------------------------
    user_1 = randomizer.generate_random_user()
    user_1.last_online = datetime.datetime.utcnow()
    session.commit()
    # --------------------------------------------------------------------------

    response: Response = await client.get(
        f"{settings.API_V1_PREFIX}/users/{user_1.id}",
        headers=default_user_auth_headers
    )
    assert response.status_code == 200
    resp_data = response.json()
    assert not resp_data['online']


@pytest.mark.anyio
async def test_user_fetch_single(
        client: AsyncClient,
        default_user: User,
        randomizer: RandomEntityGenerator,
        session: Session,
        redis_user: RedisUserCacheService,
        default_user_auth_headers: dict[str, str]):
    # not cached
    assert not await redis_user.get_user(str(default_user.id))

    response: Response = await client.get(
        f"{settings.API_V1_PREFIX}/users/{default_user.id}",
        headers=default_user_auth_headers
    )
    # cached
    assert await redis_user.get_user(str(default_user.id))


@pytest.mark.anyio
async def test_user_fetch_deactivated(
        client: AsyncClient,
        default_user: User,
        randomizer: RandomEntityGenerator,
        session: Session,
        default_user_auth_headers: dict[str, str]):
    user_1 = randomizer.generate_random_user()
    user_1.deactivation_date = datetime.datetime.utcnow()
    session.commit()
    response: Response = await client.get(
        f"{settings.API_V1_PREFIX}/users/{user_1.id}",
        headers=default_user_auth_headers
    )
    assert response.status_code == 409


@pytest.mark.anyio
async def test_user_fetch_all_deactivated(
        client: AsyncClient,
        default_user: User,
        randomizer: RandomEntityGenerator,
        session: Session,
        default_user_auth_headers: dict[str, str]):
    user_1 = randomizer.generate_random_user()
    user_1.deactivation_date = datetime.datetime.utcnow()
    session.commit()

    since = datetime.datetime.utcnow() - datetime.timedelta(days=1)
    response: Response = await client.get(
        f"{settings.API_V1_PREFIX}/users/deactivated",
        params={
            'since': since.isoformat()
        },
        headers=default_user_auth_headers
    )
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0] == str(user_1.id)
