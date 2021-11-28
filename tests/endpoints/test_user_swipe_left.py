import pytest
from httpx import AsyncClient
from pytest_mock import MockerFixture
from sqlalchemy.orm import Session

from swipe.settings import settings
from swipe.swipe_server.misc.randomizer import RandomEntityGenerator
from swipe.swipe_server.users.models import User
from swipe.swipe_server.users.redis_services import RedisBlacklistService
from swipe.swipe_server.users.services import UserService


@pytest.mark.anyio
async def test_swipe_left_enough_swipes(
        client: AsyncClient,
        default_user: User,
        user_service: UserService,
        randomizer: RandomEntityGenerator,
        session: Session,
        mocker: MockerFixture,
        redis_blacklist: RedisBlacklistService,
        default_user_auth_headers: dict[str, str]):
    requests_mock = \
        mocker.patch('swipe.swipe_server.users.services.requests')
    other_user = randomizer.generate_random_user()
    session.commit()

    previous_swipes = other_user.swipes
    response = await client.post(
        f"{settings.API_V1_PREFIX}/users/{other_user.id}/swipe_left",
        headers=default_user_auth_headers)
    session.refresh(default_user)
    assert other_user.swipes == previous_swipes - 1

    assert response.status_code == 204
    assert len(default_user.blacklist) == 1
    assert other_user in default_user.blacklist
    assert default_user in other_user.blocked_by

    assert await redis_blacklist.get_blacklist(default_user.id) == \
           {str(other_user.id)}
    assert await redis_blacklist.get_blacklist(other_user.id) == \
           {str(default_user.id)}
    url = f'{settings.CHAT_SERVER_HOST}/swipe/blacklist'
    requests_mock.post.assert_called_with(url, json={
        'blocked_by_id': str(default_user.id),
        'blocked_user_id': str(other_user.id)
    })


@pytest.mark.anyio
async def test_swipe_left_not_enough_swipes(
        client: AsyncClient,
        default_user: User,
        user_service: UserService,
        randomizer: RandomEntityGenerator,
        session: Session,
        mocker: MockerFixture,
        redis_blacklist: RedisBlacklistService,
        default_user_auth_headers: dict[str, str]):
    requests_mock = \
        mocker.patch('swipe.swipe_server.users.services.requests')
    other_user = randomizer.generate_random_user()
    other_user.swipes = 0
    session.commit()

    response = await client.post(
        f"{settings.API_V1_PREFIX}/users/{other_user.id}/swipe_left",
        headers=default_user_auth_headers)

    assert response.status_code == 409
    assert other_user not in default_user.blacklist
    assert default_user not in other_user.blocked_by

    assert await redis_blacklist.get_blacklist(default_user.id) == set()
    assert await redis_blacklist.get_blacklist(other_user.id) == set()
    requests_mock.post.assert_not_called()
