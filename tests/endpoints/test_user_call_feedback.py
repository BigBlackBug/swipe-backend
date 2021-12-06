import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from swipe.settings import settings
from swipe.swipe_server.misc.randomizer import RandomEntityGenerator
from swipe.swipe_server.users.models import User
from swipe.swipe_server.users.services.services import UserService


@pytest.mark.anyio
async def test_add_positive_feedback(
        client: AsyncClient,
        default_user: User,
        user_service: UserService,
        randomizer: RandomEntityGenerator,
        session: Session,
        default_user_auth_headers: dict[str, str]):
    other_user = randomizer.generate_random_user()
    session.commit()

    previous_rating = other_user.rating
    await client.post(
        f"{settings.API_V1_PREFIX}/users/{other_user.id}/call_feedback",
        json={
            'feedback': 'thumbs_up'
        },
        headers=default_user_auth_headers)

    other_user = user_service.get_user(other_user.id)
    assert other_user.rating > previous_rating


@pytest.mark.anyio
async def test_add_negative_feedback(
        client: AsyncClient,
        default_user: User,
        user_service: UserService,
        randomizer: RandomEntityGenerator,
        session: Session,
        default_user_auth_headers: dict[str, str]):
    other_user = randomizer.generate_random_user()
    session.commit()

    previous_rating = other_user.rating
    await client.post(
        f"{settings.API_V1_PREFIX}/users/{other_user.id}/call_feedback",
        json={
            'feedback': 'thumbs_down'
        },
        headers=default_user_auth_headers)

    other_user = user_service.get_user(other_user.id)
    assert other_user.rating < previous_rating


@pytest.mark.anyio
async def test_add_negative_below_zero_feedback(
        client: AsyncClient,
        default_user: User,
        user_service: UserService,
        randomizer: RandomEntityGenerator,
        session: Session,
        default_user_auth_headers: dict[str, str]):
    other_user = randomizer.generate_random_user()
    other_user.rating = 0
    session.commit()

    await client.post(
        f"{settings.API_V1_PREFIX}/users/{other_user.id}/call_feedback",
        json={
            'feedback': 'thumbs_down'
        },
        headers=default_user_auth_headers)

    other_user = user_service.get_user(other_user.id)
    assert other_user.rating == 0
