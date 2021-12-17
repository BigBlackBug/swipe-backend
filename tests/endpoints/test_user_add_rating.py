import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from swipe.settings import settings
from swipe.swipe_server.misc.randomizer import RandomEntityGenerator
from swipe.swipe_server.users.models import User
from swipe.swipe_server.users.services.redis_services import RedisBlacklistService
from swipe.swipe_server.users.services.user_service import UserService


@pytest.mark.anyio
async def test_user_add_rating(
        client: AsyncClient,
        default_user: User,
        user_service: UserService,
        randomizer: RandomEntityGenerator,
        session: Session,
        redis_blacklist: RedisBlacklistService,
        default_user_auth_headers: dict[str, str]):
    old_rating = default_user.rating
    response = await client.post(
        f"{settings.API_V1_PREFIX}/me/rating",
        json={
            'reason': 'ad_watched'
        },
        headers=default_user_auth_headers)
    assert response.status_code == 200

    session.refresh(default_user)

    assert default_user.rating > old_rating
    assert response.json()['rating'] == default_user.rating
