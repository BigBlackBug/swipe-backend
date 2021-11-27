import datetime

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.orm import Session

from swipe.settings import settings
from swipe.swipe_server.chats.models import Chat, ChatStatus, ChatMessage, \
    MessageStatus, \
    ChatSource
from swipe.swipe_server.misc.randomizer import RandomEntityGenerator
from swipe.swipe_server.users import models


@pytest.mark.anyio
async def test_fetch_existing_chats(
        client: AsyncClient,
        default_user: models.User,
        session: Session,
        randomizer: RandomEntityGenerator,
        default_user_auth_headers: dict[str, str]):
    other_user = randomizer.generate_random_user()
    older_chat = Chat(
        status=ChatStatus.ACCEPTED,
        source=ChatSource.VIDEO_LOBBY,
        initiator=other_user,
        the_other_person=default_user)
    session.add(older_chat)

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
    older_chat.messages.extend([msg1, msg2, msg3, msg4])

    # chat with unread messages
    second_user = randomizer.generate_random_user()
    newer_chat = Chat(
        status=ChatStatus.ACCEPTED, source=ChatSource.VIDEO_LOBBY,
        initiator=default_user,
        the_other_person=second_user)
    session.add(newer_chat)

    msg5 = ChatMessage(
        timestamp=datetime.datetime.now(), status=MessageStatus.READ,
        message='wtf omg lol', sender=default_user)
    msg6 = ChatMessage(
        timestamp=datetime.datetime.now(), status=MessageStatus.RECEIVED,
        message='fuck off', sender=second_user)
    msg7 = ChatMessage(
        timestamp=datetime.datetime.now(), status=MessageStatus.RECEIVED,
        image_id='345345.png', sender=default_user)
    newer_chat.messages.extend([msg5, msg6, msg7])
    session.commit()

    # --------------------------------------------------------
    response: Response = await client.get(
        f"{settings.API_V1_PREFIX}/me/chats",
        headers=default_user_auth_headers
    )
    assert response.status_code == 200

    users = response.json()['users']
    assert len(users) == 3
    assert set(users.keys()) == {
        str(default_user.id), str(other_user.id), str(second_user.id)
    }
    assert users[str(default_user.id)]['name'] == default_user.name
    assert users[str(other_user.id)]['name'] == other_user.name
    assert users[str(second_user.id)]['name'] == second_user.name

    chats = response.json()['chats']
    assert len(chats) == 2

    # newer_chat goes first since he was created later
    # default_user fetches the chat, so the_other_person_id is second_user
    assert chats[0]['id'] == str(newer_chat.id)
    assert chats[0]['the_other_person_id'] == str(second_user.id)

    messages = chats[0]['messages']
    assert len(messages) == 3
    assert messages[0]['id'] == str(msg5.id)
    assert messages[1]['id'] == str(msg6.id)
    assert messages[2]['id'] == str(msg7.id)

    assert messages[1]['message'] == msg6.message
    assert messages[2].get('image_url')

    # -----------------------------------------------------------
    messages = chats[1]['messages']
    assert len(messages) == 4
    assert messages[0]['id'] == str(msg1.id)
    assert messages[1]['id'] == str(msg2.id)
    assert messages[2]['id'] == str(msg3.id)
    assert messages[3]['id'] == str(msg4.id)

    assert messages[1]['message'] == msg2.message
    assert messages[3].get('image_url')


@pytest.mark.anyio
async def test_fetch_existing_and_outgoing_request(
        client: AsyncClient,
        default_user: models.User,
        session: Session,
        randomizer: RandomEntityGenerator,
        default_user_auth_headers: dict[str, str]):
    other_user = randomizer.generate_random_user()
    chat = Chat(
        status=ChatStatus.ACCEPTED,
        source=ChatSource.VIDEO_LOBBY,
        initiator=other_user,
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

    # outgoing request
    second_user = randomizer.generate_random_user()
    outgoing_requets_chat = Chat(
        status=ChatStatus.REQUESTED, source=ChatSource.VIDEO_LOBBY,
        initiator=default_user,
        the_other_person=second_user)
    session.add(outgoing_requets_chat)

    msg5 = ChatMessage(
        timestamp=datetime.datetime.now(), status=MessageStatus.READ,
        message='wtf omg lol', sender=default_user)
    msg6 = ChatMessage(
        timestamp=datetime.datetime.now(), status=MessageStatus.RECEIVED,
        message='fuck off', sender=second_user)
    msg7 = ChatMessage(
        timestamp=datetime.datetime.now(), status=MessageStatus.RECEIVED,
        image_id='345345.png', sender=default_user)
    outgoing_requets_chat.messages.extend([msg5, msg6, msg7])
    session.commit()

    # -----------------------------------------------------------
    response: Response = await client.get(
        f"{settings.API_V1_PREFIX}/me/chats",
        headers=default_user_auth_headers
    )
    assert response.status_code == 200

    users = response.json()['users']
    assert len(users) == 3
    assert set(users.keys()) == {
        str(default_user.id), str(other_user.id), str(second_user.id)
    }
    assert users[str(default_user.id)]['name'] == default_user.name
    assert users[str(other_user.id)]['name'] == other_user.name
    assert users[str(second_user.id)]['name'] == second_user.name
    assert users[str(second_user.id)]['location']['city'] \
           == second_user.location.city

    chats = response.json()['chats']
    assert len(chats) == 2
    # outgoing_requets_chat goes first since he was created later
    # default_user fetches the chat, so the_other_person_id is second_user
    assert chats[0]['id'] == str(outgoing_requets_chat.id)
    assert chats[0]['the_other_person_id'] == str(second_user.id)

    messages = chats[0]['messages']
    assert len(messages) == 3
    assert messages[0]['id'] == str(msg5.id)
    assert messages[1]['id'] == str(msg6.id)
    assert messages[2]['id'] == str(msg7.id)

    assert messages[1]['message'] == msg6.message
    assert messages[2].get('image_url')

    # chat is second
    assert chats[1]['id'] == str(chat.id)
    messages = chats[1]['messages']
    assert len(messages) == 4
    assert messages[0]['id'] == str(msg1.id)
    assert messages[1]['id'] == str(msg2.id)
    assert messages[2]['id'] == str(msg3.id)
    assert messages[3]['id'] == str(msg4.id)

    assert messages[1]['message'] == msg2.message
    assert messages[3].get('image_url')

    assert len(response.json()['requests']) == 0


@pytest.mark.anyio
async def test_fetch_existing_and_incoming_request(
        client: AsyncClient,
        default_user: models.User,
        session: Session,
        randomizer: RandomEntityGenerator,
        default_user_auth_headers: dict[str, str]):
    other_user = randomizer.generate_random_user()
    chat = Chat(
        status=ChatStatus.ACCEPTED,
        source=ChatSource.VIDEO_LOBBY,
        initiator=other_user,
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

    whatever_user = randomizer.generate_random_user()
    # chat wth no messages
    chat_no_messages = Chat(
        status=ChatStatus.ACCEPTED,
        source=ChatSource.VIDEO_LOBBY,
        initiator=whatever_user,
        the_other_person=default_user)
    session.add(chat_no_messages)

    # incoming request
    second_user = randomizer.generate_random_user()
    chat_incoming_request = Chat(
        status=ChatStatus.REQUESTED, source=ChatSource.VIDEO_LOBBY,
        initiator=second_user,
        the_other_person=default_user)
    session.add(chat_incoming_request)

    msg5 = ChatMessage(
        timestamp=datetime.datetime.now(), status=MessageStatus.READ,
        message='wtf omg lol', sender=default_user)
    msg6 = ChatMessage(
        timestamp=datetime.datetime.now(), status=MessageStatus.RECEIVED,
        message='fuck off', sender=second_user)
    msg7 = ChatMessage(
        timestamp=datetime.datetime.now(), status=MessageStatus.RECEIVED,
        image_id='345345.png', sender=default_user)
    chat_incoming_request.messages.extend([msg5, msg6, msg7])
    session.commit()

    response: Response = await client.get(
        f"{settings.API_V1_PREFIX}/me/chats",
        headers=default_user_auth_headers
    )
    assert response.status_code == 200
    users = response.json()['users']
    assert len(users) == 4
    assert set(users.keys()) == {
        str(default_user.id), str(other_user.id), str(second_user.id),
        str(whatever_user.id)
    }
    assert users[str(default_user.id)]['name'] == default_user.name
    assert users[str(other_user.id)]['name'] == other_user.name
    assert users[str(second_user.id)]['name'] == second_user.name
    assert users[str(second_user.id)]['location']['city'] \
           == second_user.location.city

    chats = response.json()['chats']
    assert len(chats) == 2
    assert chats[0]['id'] == str(chat_no_messages.id)
    assert len(chats[0]['messages']) == 0

    assert chats[1]['the_other_person_id'] == str(other_user.id)

    messages = chats[1]['messages']
    assert len(messages) == 4
    assert messages[0]['id'] == str(msg1.id)
    assert messages[1]['id'] == str(msg2.id)
    assert messages[2]['id'] == str(msg3.id)
    assert messages[3]['id'] == str(msg4.id)

    assert messages[1]['message'] == msg2.message
    assert messages[3].get('image_url')

    chat_requests = response.json()['requests']
    assert len(chat_requests) == 1
    assert chat_requests[0]['id'] == str(chat_incoming_request.id)
    messages = chat_requests[0]['messages']

    assert len(messages) == 3
    assert messages[0]['id'] == str(msg5.id)
    assert messages[1]['id'] == str(msg6.id)
    assert messages[2]['id'] == str(msg7.id)

    assert messages[1]['message'] == msg6.message
    assert messages[2].get('image_url')


@pytest.mark.anyio
async def test_fetch_existing_chats_only_unread(
        client: AsyncClient,
        default_user: models.User,
        session: Session,
        randomizer: RandomEntityGenerator,
        default_user_auth_headers: dict[str, str]):
    first_user = randomizer.generate_random_user()
    # chat without unread messages
    older_chat = Chat(
        status=ChatStatus.ACCEPTED, source=ChatSource.VIDEO_LOBBY,
        initiator=first_user,
        the_other_person=default_user)
    session.add(older_chat)

    msg1 = ChatMessage(
        timestamp=datetime.datetime.now(), status=MessageStatus.READ,
        message='wtf omg lol', sender=default_user)
    msg2 = ChatMessage(
        timestamp=datetime.datetime.now(), status=MessageStatus.READ,
        message='why dont u answer me???', sender=default_user)
    msg3 = ChatMessage(
        timestamp=datetime.datetime.now(), status=MessageStatus.READ,
        message='fuck off', sender=first_user)
    msg4 = ChatMessage(
        timestamp=datetime.datetime.now(), status=MessageStatus.READ,
        image_id='345345.png', sender=first_user)
    older_chat.messages.extend([msg1, msg2, msg3, msg4])

    # chat with unread messages
    second_user = randomizer.generate_random_user()
    newer_chat = Chat(
        status=ChatStatus.ACCEPTED, source=ChatSource.VIDEO_LOBBY,
        initiator=default_user,
        the_other_person=second_user)
    session.add(newer_chat)

    msg5 = ChatMessage(
        timestamp=datetime.datetime.now(), status=MessageStatus.READ,
        message='wtf omg lol', sender=default_user)
    msg6 = ChatMessage(
        timestamp=datetime.datetime.now(), status=MessageStatus.RECEIVED,
        message='fuck off', sender=second_user)
    msg7 = ChatMessage(
        timestamp=datetime.datetime.now(), status=MessageStatus.RECEIVED,
        image_id='345345.png', sender=default_user)
    newer_chat.messages.extend([msg5, msg6, msg7])
    session.commit()

    response: Response = await client.get(
        f"{settings.API_V1_PREFIX}/me/chats",
        params={
            'only_unread': True
        },
        headers=default_user_auth_headers
    )
    assert response.status_code == 200
    users = response.json()['users']
    assert len(users) == 2
    assert set(users.keys()) == {
        str(default_user.id), str(second_user.id)
    }
    assert users[str(default_user.id)]['name'] == default_user.name
    assert users[str(second_user.id)]['name'] == second_user.name

    chat_response = response.json()['chats']
    assert len(chat_response) == 1

    assert chat_response[0]['id'] == str(newer_chat.id)
    messages = chat_response[0]['messages']
    assert len(messages) == 2
    assert messages[0]['id'] == str(msg6.id)
    assert messages[1]['id'] == str(msg7.id)

    assert messages[1]['message'] == msg7.message


@pytest.mark.anyio
async def test_fetch_single_chat(
        client: AsyncClient,
        default_user: models.User,
        session: Session,
        randomizer: RandomEntityGenerator,
        default_user_auth_headers: dict[str, str]):
    initiator = randomizer.generate_random_user()
    chat = Chat(
        status=ChatStatus.ACCEPTED, source=ChatSource.VIDEO_LOBBY,
        initiator=initiator,
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
    assert resp_data['messages'][3]['id'] == str(msg4.id)


@pytest.mark.anyio
async def test_fetch_single_chat_only_unread(
        client: AsyncClient,
        default_user: models.User,
        session: Session,
        randomizer: RandomEntityGenerator,
        default_user_auth_headers: dict[str, str]):
    initiator = randomizer.generate_random_user()
    chat = Chat(
        status=ChatStatus.ACCEPTED, source=ChatSource.VIDEO_LOBBY,
        initiator=initiator,
        the_other_person=default_user)
    session.add(chat)

    msg1 = ChatMessage(
        timestamp=datetime.datetime.now(), status=MessageStatus.READ,
        message='wtf omg lol', sender=default_user)
    msg2 = ChatMessage(
        timestamp=datetime.datetime.now(), status=MessageStatus.READ,
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
        params={
            'only_unread': True
        },
        headers=default_user_auth_headers
    )
    assert response.status_code == 200
    resp_data = response.json()
    assert resp_data['the_other_person_id'] == str(initiator.id)
    assert len(resp_data['messages']) == 2
    assert resp_data['messages'][0]['id'] == str(msg1.id)
