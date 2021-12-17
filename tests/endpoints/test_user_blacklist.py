import pytest
from httpx import Response, AsyncClient
from pytest_mock import MockerFixture
from sqlalchemy.orm import Session

from swipe.settings import settings
from swipe.swipe_server.misc.randomizer import RandomEntityGenerator
from swipe.swipe_server.users import models
from swipe.swipe_server.users.services.redis_services import RedisBlacklistService
from swipe.swipe_server.users.services.blacklist_service import BlacklistService
from swipe.swipe_server.users.services.user_service import UserService


@pytest.mark.anyio
async def test_add_to_blacklist(
        session: Session,
        randomizer: RandomEntityGenerator,
        client: AsyncClient,
        redis_blacklist: RedisBlacklistService,
        blacklist_service: BlacklistService,
        user_service: UserService,
        mocker: MockerFixture,
        default_user: models.User,
        default_user_auth_headers: dict[str, str]):
    # --------------------------------------------------------------------------
    user_1 = randomizer.generate_random_user()
    user_2 = randomizer.generate_random_user()
    user_3 = randomizer.generate_random_user()
    session.commit()

    mock_events = mocker.patch('swipe.swipe_server.users.'
                               'services.blacklist_service.events')
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/{user_1.id}/block",
        headers=default_user_auth_headers
    )
    mock_events.send_blacklist_event.assert_called_with(
        str(default_user.id), str(user_1.id))

    assert response.status_code == 204
    assert len(default_user.blacklist) == 1
    assert user_1 in default_user.blacklist
    assert default_user in user_1.blocked_by

    # ----------------------------------------------------------------
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/{user_2.id}/block",
        headers=default_user_auth_headers
    )
    assert response.status_code == 204
    assert len(default_user.blacklist) == 2
    assert user_2 in default_user.blacklist
    assert default_user in user_2.blocked_by

    mock_events.send_blacklist_event.assert_called_with(
        str(default_user.id), str(user_2.id))

    # ----------------------------------------------------------------
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/{user_3.id}/block",
        headers=default_user_auth_headers
    )
    assert response.status_code == 204
    assert len(default_user.blacklist) == 3
    assert user_3 in default_user.blacklist
    assert default_user in user_3.blocked_by

    mock_events.send_blacklist_event.assert_called_with(
        str(default_user.id), str(user_3.id))

    # --------------------------------------------------------

    assert await redis_blacklist.get_blacklist(str(default_user.id)) == \
           {str(user_1.id), str(user_2.id), str(user_3.id)}
    blacklist = await user_service.fetch_blacklist(str(default_user.id))

    assert blacklist == {str(user_1.id), str(user_2.id), str(user_3.id)}
    # 409 on repeated block
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/{user_3.id}/block",
        headers=default_user_auth_headers
    )
    assert response.status_code == 409
