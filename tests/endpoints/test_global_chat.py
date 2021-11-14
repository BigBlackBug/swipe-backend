import datetime

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.orm import Session

from swipe.settings import settings
from swipe.swipe_server.chats.models import GlobalChatMessage
from swipe.swipe_server.misc.randomizer import RandomEntityGenerator
from swipe.swipe_server.users import models


@pytest.mark.anyio
async def test_fetch_global_chat(
        client: AsyncClient,
        default_user: models.User,
        session: Session,
        randomizer: RandomEntityGenerator,
        default_user_auth_headers: dict[str, str]):
    other_user = randomizer.generate_random_user()
    another_user = randomizer.generate_random_user()

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

    response_data = response.json()
    assert 'users' in response_data
    assert 'messages' in response_data

    messages = response_data['messages']
    assert len(messages) == 4

    assert messages[0]['id'] == str(msg4.id)
    assert messages[1]['id'] == str(msg3.id)
    assert messages[2]['id'] == str(msg2.id)
    assert messages[3]['id'] == str(msg1.id)

    assert messages[1]['message'] == msg3.message

    users: dict = response_data['users']
    assert len(users) == 3
    assert set(users.keys()) == {
        str(default_user.id), str(other_user.id), str(another_user.id)
    }
    assert users[str(default_user.id)]['name'] == default_user.name
    assert users[str(another_user.id)]['name'] == another_user.name
    assert users[str(other_user.id)]['name'] == other_user.name


@pytest.mark.anyio
async def test_fetch_global_chat_from_id(
        client: AsyncClient,
        default_user: models.User,
        session: Session,
        randomizer: RandomEntityGenerator,
        default_user_auth_headers: dict[str, str]):
    other_user = randomizer.generate_random_user()
    another_user = randomizer.generate_random_user()

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

    response_data = response.json()
    assert 'users' in response_data
    assert 'messages' in response_data

    messages = response_data['messages']
    assert len(messages) == 3

    assert messages[0]['id'] == str(msg4.id)
    assert messages[1]['id'] == str(msg3.id)
    assert messages[2]['id'] == str(msg2.id)

    assert messages[1]['message'] == msg3.message

    users: dict = response_data['users']
    assert len(users) == 3
    assert set(users.keys()) == {
        str(default_user.id), str(other_user.id), str(another_user.id)
    }
    assert users[str(default_user.id)]['name'] == default_user.name
    assert users[str(another_user.id)]['name'] == another_user.name
    assert users[str(other_user.id)]['name'] == other_user.name
