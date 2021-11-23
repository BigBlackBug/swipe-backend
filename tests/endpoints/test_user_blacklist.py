import uuid

import pytest
from httpx import Response, AsyncClient
from sqlalchemy.orm import Session

from swipe.settings import settings
from swipe.swipe_server.misc.randomizer import RandomEntityGenerator
from swipe.swipe_server.users import models
from swipe.swipe_server.users.services import RedisUserService, UserService


@pytest.mark.anyio
async def test_blacklist(
        session: Session,
        randomizer: RandomEntityGenerator,
        client: AsyncClient,
        redis_service: RedisUserService,
        user_service: UserService,
        default_user: models.User,
        default_user_auth_headers: dict[str, str]):
    # --------------------------------------------------------------------------
    user_1 = randomizer.generate_random_user()
    user_2 = randomizer.generate_random_user()
    user_3 = randomizer.generate_random_user()
    session.commit()

    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/{user_1.id}/block",
        headers=default_user_auth_headers
    )
    assert response.status_code == 204
    assert len(default_user.blacklist) == 1
    assert user_1 in default_user.blacklist
    assert default_user in user_1.blocked_by

    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/{user_2.id}/block",
        headers=default_user_auth_headers
    )
    assert response.status_code == 204
    assert len(default_user.blacklist) == 2
    assert user_2 in default_user.blacklist
    assert default_user in user_2.blocked_by

    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/{user_3.id}/block",
        headers=default_user_auth_headers
    )
    assert response.status_code == 204
    assert len(default_user.blacklist) == 3
    assert user_3 in default_user.blacklist
    assert default_user in user_3.blocked_by

    assert await redis_service.get_blacklist(default_user.id) == \
           {str(user_1.id), str(user_2.id), str(user_3.id)}
    blacklist = user_service.fetch_blacklist(str(default_user.id))
    assert blacklist == {str(user_1.id), str(user_2.id), str(user_3.id)}
    # 409 on repeated block
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/{user_3.id}/block",
        headers=default_user_auth_headers
    )
    assert response.status_code == 409
