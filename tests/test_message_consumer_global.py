import datetime
import uuid

import pytest
from httpx import AsyncClient, Response

from swipe.chats.models import GlobalChatMessage, Chat, ChatMessage, \
    MessageStatus, ChatStatus, ChatSource
from swipe.chats.services import ChatService
from swipe.randomizer import RandomEntityGenerator
from swipe.users import models

NOW = datetime.datetime.now()


@pytest.mark.anyio
async def test_post_global_message(
        mc_client: AsyncClient,
        default_user: models.User,
        chat_service: ChatService,
        default_user_auth_headers: dict[str, str]):
    message_id = uuid.uuid4()

    response: Response = await mc_client.post(
        f"/global",
        json={
            'timestamp': NOW.isoformat(),
            'sender': str(default_user.id),
            'payload': {
                'type': 'message',
                'message_id': str(message_id),
                'text': 'hello'
            }
        },
        headers=default_user_auth_headers
    )

    assert response.status_code == 200

    global_messages: list[GlobalChatMessage] = chat_service.fetch_global_chat()
    assert len(global_messages) == 1
    assert global_messages[0].id == message_id


@pytest.mark.anyio
async def test_post_directed_message(
        mc_client: AsyncClient,
        default_user: models.User,
        chat_service: ChatService,
        randomizer: RandomEntityGenerator,
        default_user_auth_headers: dict[str, str]):
    recipient = randomizer.generate_random_user()
    chat_id = uuid.uuid4()
    chat_service.create_chat(
        chat_id=chat_id, initiator_id=default_user.id,
        the_other_person_id=recipient.id,
        chat_status=ChatStatus.ACCEPTED, source=ChatSource.VIDEO_LOBBY)
    message_id = uuid.uuid4()
    response: Response = await mc_client.post(
        f"/global",
        json={
            'timestamp': NOW.isoformat(),
            'sender': str(default_user.id),
            'recipient': str(recipient.id),
            'payload': {
                'type': 'message',
                'message_id': str(message_id),
                'text': 'hello'
            }
        },
        headers=default_user_auth_headers
    )

    assert response.status_code == 200

    chat: Chat = \
        chat_service.fetch_chat_by_members(recipient.id, default_user.id)
    assert len(chat.messages) == 1
    assert chat.messages[0].sender == default_user
    assert chat.initiator == default_user
    assert chat.the_other_person == recipient


@pytest.mark.anyio
async def test_set_received_status(
        mc_client: AsyncClient,
        default_user: models.User,
        chat_service: ChatService,
        randomizer: RandomEntityGenerator,
        default_user_auth_headers: dict[str, str]):
    recipient = randomizer.generate_random_user()
    message_id = uuid.uuid4()
    chat_id = uuid.uuid4()
    chat_service.create_chat(
        chat_id=chat_id, initiator_id=default_user.id,
        the_other_person_id=recipient.id,
        chat_status=ChatStatus.ACCEPTED, source=ChatSource.VIDEO_LOBBY)
    chat_service.post_message(
        message_id, default_user.id, recipient.id,
        timestamp=NOW, message='what', is_liked=False)

    response: Response = await mc_client.post(
        f"/global",
        json={
            'timestamp': NOW.isoformat(),
            'sender': str(default_user.id),
            'payload': {
                'type': 'message_status',
                'message_id': str(message_id),
                'status': 'RECEIVED'
            }
        },
        headers=default_user_auth_headers
    )

    assert response.status_code == 200

    chat = chat_service.fetch_chat(chat_id)
    assert len(chat.messages) == 1
    message: ChatMessage = chat_service.fetch_message(message_id)
    assert message.status == MessageStatus.RECEIVED


@pytest.mark.anyio
async def test_set_read_status(
        mc_client: AsyncClient,
        default_user: models.User,
        chat_service: ChatService,
        randomizer: RandomEntityGenerator,
        default_user_auth_headers: dict[str, str]):
    recipient = randomizer.generate_random_user()
    message_id = uuid.uuid4()
    chat_id = uuid.uuid4()
    chat_service.create_chat(
        chat_id=chat_id, initiator_id=default_user.id,
        the_other_person_id=recipient.id,
        chat_status=ChatStatus.ACCEPTED, source=ChatSource.VIDEO_LOBBY)
    chat_service.post_message(
        message_id, default_user.id, recipient.id,
        timestamp=NOW, message='what', is_liked=False)
    response: Response = await mc_client.post(
        f"/global",
        json={
            'timestamp': NOW.isoformat(),
            'sender': str(default_user.id),
            'payload': {
                'type': 'message_status',
                'message_id': str(message_id),
                'status': 'READ'
            }
        },
        headers=default_user_auth_headers
    )

    assert response.status_code == 200

    message: ChatMessage = chat_service.fetch_message(message_id)
    assert message.status == MessageStatus.READ


@pytest.mark.anyio
async def test_set_liked(
        mc_client: AsyncClient,
        default_user: models.User,
        chat_service: ChatService,
        randomizer: RandomEntityGenerator,
        default_user_auth_headers: dict[str, str]):
    recipient = randomizer.generate_random_user()
    message_id = uuid.uuid4()
    chat_id = uuid.uuid4()
    chat_service.create_chat(
        chat_id=chat_id, initiator_id=default_user.id,
        the_other_person_id=recipient.id,
        chat_status=ChatStatus.ACCEPTED, source=ChatSource.VIDEO_LOBBY)
    chat_service.post_message(
        message_id, default_user.id, recipient.id,
        timestamp=NOW, message='what', is_liked=False)
    response: Response = await mc_client.post(
        f"/global",
        json={
            'timestamp': NOW.isoformat(),
            'sender': str(default_user.id),
            'payload': {
                'type': 'like',
                'message_id': str(message_id),
                'status': True
            }
        },
        headers=default_user_auth_headers
    )

    assert response.status_code == 200

    message: ChatMessage = chat_service.fetch_message(message_id)
    assert message.is_liked


@pytest.mark.anyio
async def test_set_disliked(
        mc_client: AsyncClient,
        default_user: models.User,
        chat_service: ChatService,
        randomizer: RandomEntityGenerator,
        default_user_auth_headers: dict[str, str]):
    recipient = randomizer.generate_random_user()
    message_id = uuid.uuid4()
    chat_id = uuid.uuid4()
    chat_service.create_chat(
        chat_id=chat_id, initiator_id=default_user.id,
        the_other_person_id=recipient.id,
        chat_status=ChatStatus.ACCEPTED, source=ChatSource.VIDEO_LOBBY)
    chat_service.post_message(
        message_id, default_user.id, recipient.id,
        timestamp=NOW, message='what', is_liked=True)
    response: Response = await mc_client.post(
        f"/global",
        json={
            'timestamp': NOW.isoformat(),
            'sender': str(default_user.id),
            'payload': {
                'type': 'like',
                'message_id': str(message_id),
                'status': False
            }
        },
        headers=default_user_auth_headers
    )

    assert response.status_code == 200

    message: ChatMessage = chat_service.fetch_message(message_id)
    assert not message.is_liked


@pytest.mark.anyio
async def test_create_chat_direct(
        mc_client: AsyncClient,
        default_user: models.User,
        chat_service: ChatService,
        randomizer: RandomEntityGenerator,
        default_user_auth_headers: dict[str, str]):
    recipient = randomizer.generate_random_user()
    chat_id = uuid.uuid4()
    response: Response = await mc_client.post(
        f"/global",
        json={
            'timestamp': NOW.isoformat(),
            'sender': str(default_user.id),
            'recipient': str(recipient.id),
            'payload': {
                'type': 'create_chat',
                'source': ChatSource.DIRECT,
                'chat_id': str(chat_id),
                'message': {
                    'message_id': str(uuid.uuid4()),
                    'sender': str(default_user.id),
                    'recipient': str(recipient.id),
                    'timestamp': NOW.isoformat(),
                    'text': 'hello'
                }
            }
        },
        headers=default_user_auth_headers
    )

    assert response.status_code == 200

    chat: Chat = chat_service.fetch_chat(chat_id)
    # direct chats are created 'requested'
    assert chat.source == ChatSource.DIRECT
    assert chat.status == ChatStatus.REQUESTED
    assert chat.initiator_id == default_user.id
    assert chat.the_other_person_id == recipient.id
    assert len(chat.messages) == 1
    assert chat.messages[0].message == 'hello'


@pytest.mark.anyio
async def test_create_chat_text_lobby(
        mc_client: AsyncClient,
        default_user: models.User,
        chat_service: ChatService,
        randomizer: RandomEntityGenerator,
        default_user_auth_headers: dict[str, str]):
    recipient = randomizer.generate_random_user()
    chat_id = uuid.uuid4()
    response: Response = await mc_client.post(
        f"/global",
        json={
            'timestamp': NOW.isoformat(),
            'sender': str(default_user.id),
            'recipient': str(recipient.id),
            'payload': {
                'type': 'create_chat',
                'source': ChatSource.TEXT_LOBBY,
                'chat_id': str(chat_id),
                'messages': [{
                    'message_id': str(uuid.uuid4()),
                    'sender': str(default_user.id),
                    'recipient': str(recipient.id),
                    'timestamp': NOW.isoformat(),
                    'text': 'hello'
                } for _ in range(5)]
            }
        },
        headers=default_user_auth_headers
    )

    assert response.status_code == 200

    chat: Chat = chat_service.fetch_chat(chat_id)
    # lobby chats are accepted from the beginning
    assert chat.source == ChatSource.TEXT_LOBBY
    assert chat.status == ChatStatus.ACCEPTED
    assert chat.initiator_id == default_user.id
    assert chat.the_other_person_id == recipient.id
    assert len(chat.messages) == 5
    assert chat.messages[3].message == 'hello'


@pytest.mark.anyio
async def test_create_chat_audio_lobby(
        mc_client: AsyncClient,
        default_user: models.User,
        chat_service: ChatService,
        randomizer: RandomEntityGenerator,
        default_user_auth_headers: dict[str, str]):
    recipient = randomizer.generate_random_user()
    chat_id = uuid.uuid4()
    response: Response = await mc_client.post(
        f"/global",
        json={
            'timestamp': NOW.isoformat(),
            'sender': str(default_user.id),
            'recipient': str(recipient.id),
            'payload': {
                'type': 'create_chat',
                'source': ChatSource.VIDEO_LOBBY,
                'chat_id': str(chat_id),
            }
        },
        headers=default_user_auth_headers
    )

    assert response.status_code == 200

    chat: Chat = chat_service.fetch_chat(chat_id)
    # lobby chats are accepted from the beginning
    assert chat.source == ChatSource.VIDEO_LOBBY
    assert chat.status == ChatStatus.ACCEPTED
    assert chat.initiator_id == default_user.id
    assert chat.the_other_person_id == recipient.id
    assert len(chat.messages) == 0


@pytest.mark.anyio
async def test_create_chat_video_lobby(
        mc_client: AsyncClient,
        default_user: models.User,
        chat_service: ChatService,
        randomizer: RandomEntityGenerator,
        default_user_auth_headers: dict[str, str]):
    recipient = randomizer.generate_random_user()
    chat_id = uuid.uuid4()
    response: Response = await mc_client.post(
        f"/global",
        json={
            'timestamp': NOW.isoformat(),
            'sender': str(default_user.id),
            'recipient': str(recipient.id),
            'payload': {
                'type': 'create_chat',
                'source': ChatSource.AUDIO_LOBBY,
                'chat_id': str(chat_id),
            }
        },
        headers=default_user_auth_headers
    )

    assert response.status_code == 200

    chat: Chat = chat_service.fetch_chat(chat_id)
    # lobby chats are accepted from the beginning
    assert chat.source == ChatSource.AUDIO_LOBBY
    assert chat.status == ChatStatus.ACCEPTED
    assert chat.initiator_id == default_user.id
    assert chat.the_other_person_id == recipient.id
    assert len(chat.messages) == 0
