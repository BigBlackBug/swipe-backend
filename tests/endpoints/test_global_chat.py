import datetime

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.orm import Session

from settings import settings
from swipe.chats.models import GlobalChatMessage
from swipe.users import models
from swipe.users.services import UserService


@pytest.mark.anyio
async def test_fetch_global_chat(
        client: AsyncClient,
        default_user: models.User,
        session: Session,
        user_service: UserService,
        default_user_auth_headers: dict[str, str]):
    other_user = user_service.generate_random_user()
    another_user = user_service.generate_random_user()

    msg1 = GlobalChatMessage(
        timestamp=datetime.datetime.now(),
        message='wtf omg lol', sender=default_user)
    msg2 = GlobalChatMessage(
        timestamp=datetime.datetime.now(),
        message='why dont u answer me???', sender=default_user)
    msg3 = GlobalChatMessage(
        timestamp=datetime.datetime.now(),
        message='fuck off', sender=other_user)
    msg4 = GlobalChatMessage(
        timestamp=datetime.datetime.now(), message='what..',
        sender=another_user)
    session.add(msg1)
    session.add(msg2)
    session.add(msg3)
    session.add(msg4)
    session.commit()

    response: Response = await client.get(
        f"{settings.API_V1_PREFIX}/me/chats/global",
        headers=default_user_auth_headers
    )
    assert response.status_code == 200
    messages = response.json()
    assert len(response.json()) == 4

    assert messages[0]['id'] == str(msg4.id)
    assert messages[1]['id'] == str(msg3.id)
    assert messages[2]['id'] == str(msg2.id)
    assert messages[3]['id'] == str(msg1.id)

    assert messages[1]['message'] == msg3.message


@pytest.mark.anyio
async def test_fetch_global_chat_from_id(
        client: AsyncClient,
        default_user: models.User,
        session: Session,
        user_service: UserService,
        default_user_auth_headers: dict[str, str]):
    other_user = user_service.generate_random_user()
    another_user = user_service.generate_random_user()

    msg1 = GlobalChatMessage(
        timestamp=datetime.datetime.now(),
        message='wtf omg lol', sender=default_user)
    msg2 = GlobalChatMessage(
        timestamp=datetime.datetime.now(),
        message='why dont u answer me???', sender=default_user)
    msg3 = GlobalChatMessage(
        timestamp=datetime.datetime.now(),
        message='fuck off', sender=other_user)
    msg4 = GlobalChatMessage(
        timestamp=datetime.datetime.now(), message='what..',
        sender=another_user)
    session.add(msg1)
    session.add(msg2)
    session.add(msg3)
    session.add(msg4)
    session.commit()

    response: Response = await client.get(
        f"{settings.API_V1_PREFIX}/me/chats/global",
        params={
            'last_message_id': str(msg1.id)
        },
        headers=default_user_auth_headers
    )
    assert response.status_code == 200
    messages = response.json()
    assert len(response.json()) == 3

    assert messages[0]['id'] == str(msg4.id)
    assert messages[1]['id'] == str(msg3.id)
    assert messages[2]['id'] == str(msg2.id)

    assert messages[1]['message'] == msg3.message
