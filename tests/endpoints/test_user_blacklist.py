import uuid

import pytest
from httpx import Response, AsyncClient
from sqlalchemy.orm import Session

from settings import settings
from swipe.randomizer import RandomEntityGenerator
from swipe.users import models


@pytest.mark.anyio
async def test_blacklist(
        session: Session,
        randomizer: RandomEntityGenerator,
        client: AsyncClient,
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

    # 409 on repeated block
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/{user_3.id}/block",
        headers=default_user_auth_headers
    )
    assert response.status_code == 409

    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/{uuid.uuid4()}/block",
        headers=default_user_auth_headers
    )
    assert response.status_code == 404
