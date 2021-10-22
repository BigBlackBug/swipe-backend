import datetime

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.orm import Session

from settings import settings
from swipe.chats.models import Chat, ChatStatus, ChatMessage, MessageStatus
from swipe.users import models
from swipe.users.services import UserService


@pytest.mark.anyio
async def test_fetch_existing_chats(
        client: AsyncClient,
        default_user: models.User,
        session: Session,
        user_service: UserService,
        default_user_auth_headers: dict[str, str]):
    other_user = user_service.generate_random_user()
    chat = Chat(
        status=ChatStatus.ACCEPTED, initiator=other_user,
        the_other_person=default_user)
    session.add(chat)

    msg1 = ChatMessage(
        timestamp=datetime.datetime.now(), status=MessageStatus.SENT,
        message='wtf omg lol', sender=default_user)
    msg2 = ChatMessage(
        timestamp=datetime.datetime.now(), status=MessageStatus.SENT,
        message='why dont u answer me???', sender=default_user)
    msg3 = ChatMessage(
        timestamp=datetime.datetime.now(), status=MessageStatus.SENT,
        message='fuck off', sender=other_user)
    msg4 = ChatMessage(
        timestamp=datetime.datetime.now(), status=MessageStatus.SENT,
        image_id='345345.png', sender=other_user)
    chat.messages.extend([msg1, msg2, msg3, msg4])
    session.commit()

    response: Response = await client.get(
        f"{settings.API_V1_PREFIX}/me/chats",
        headers=default_user_auth_headers
    )
    assert response.status_code == 200
    assert len(response.json()['chats']) == 1

    assert response.json()['chats'][0]['the_other_person_id'] \
           == str(other_user.id)

    messages = response.json()['chats'][0]['messages']
    assert len(messages) == 4
    assert messages[0]['id'] == str(msg4.id)
    assert messages[1]['id'] == str(msg3.id)
    assert messages[2]['id'] == str(msg2.id)
    assert messages[3]['id'] == str(msg1.id)

    assert messages[1]['message'] == msg3.message
    assert messages[0].get('image_url')


@pytest.mark.anyio
async def test_fetch_single_chat(
        client: AsyncClient,
        default_user: models.User,
        session: Session,
        user_service: UserService,
        default_user_auth_headers: dict[str, str]):
    initiator = user_service.generate_random_user()
    chat = Chat(
        status=ChatStatus.ACCEPTED, initiator=initiator,
        the_other_person=default_user)
    session.add(chat)

    msg1 = ChatMessage(
        timestamp=datetime.datetime.now(), status=MessageStatus.SENT,
        message='wtf omg lol', sender=default_user)
    msg2 = ChatMessage(
        timestamp=datetime.datetime.now(), status=MessageStatus.SENT,
        message='why dont u answer me???', sender=default_user)
    msg3 = ChatMessage(
        timestamp=datetime.datetime.now(), status=MessageStatus.SENT,
        message='fuck off', sender=initiator)
    msg4 = ChatMessage(
        timestamp=datetime.datetime.now(), status=MessageStatus.SENT,
        image_id='345345.png', sender=initiator)
    chat.messages.extend([msg1, msg2, msg3, msg4])
    session.commit()

    response: Response = await client.get(
        f"{settings.API_V1_PREFIX}/me/chats/{chat.id}",
        headers=default_user_auth_headers
    )
    assert response.status_code == 200
    resp_data = response.json()
    assert resp_data['the_other_person_id'] == str(initiator.id)
    assert len(resp_data['messages']) == 4
    assert resp_data['messages'][3]['id'] == str(msg1.id)
