import datetime
import uuid
from unittest.mock import MagicMock

import pytest
from fakeredis import aioredis
from pytest_mock import MockerFixture
from sqlalchemy.orm import Session

from swipe.chat_server.schemas import BasePayload
from swipe.chat_server.services import ChatServerRequestProcessor
from swipe.swipe_server.chats.models import GlobalChatMessage, Chat, \
    ChatMessage, \
    MessageStatus, ChatStatus, ChatSource
from swipe.swipe_server.chats.services import ChatService
from swipe.swipe_server.misc.randomizer import RandomEntityGenerator
from swipe.swipe_server.users import models
from swipe.swipe_server.users.services.redis_services import \
    RedisBlacklistService, RedisChatCacheService
from swipe.swipe_server.users.services.services import UserService

NOW = datetime.datetime.now()


@pytest.mark.anyio
async def test_post_global_message(
        default_user: models.User,
        chat_service: ChatService, user_service: UserService,
        fake_redis: aioredis.FakeRedis, session: Session,
        default_user_auth_headers: dict[str, str]):
    message_id = uuid.uuid4()
    mp = ChatServerRequestProcessor(session, fake_redis)
    json_data = BasePayload.validate({
        'sender_id': str(default_user.id),
        'payload': {
            'type': 'global_message',
            'timestamp': NOW.isoformat(),
            'message_id': str(message_id),
            'text': 'hello'
        }
    })
    await mp.process(json_data)

    global_messages: list[GlobalChatMessage] = chat_service.fetch_global_chat()
    assert len(global_messages) == 1
    assert global_messages[0].id == message_id


@pytest.mark.anyio
async def test_post_directed_message(
        default_user: models.User,
        chat_service: ChatService, user_service: UserService,
        fake_redis: aioredis.FakeRedis, session: Session,
        randomizer: RandomEntityGenerator,
        default_user_auth_headers: dict[str, str]):
    recipient = randomizer.generate_random_user()
    chat_id = uuid.uuid4()
    chat_service.create_chat(
        chat_id=chat_id, initiator_id=default_user.id,
        the_other_person_id=recipient.id,
        chat_status=ChatStatus.ACCEPTED, source=ChatSource.VIDEO_LOBBY)
    message_id = uuid.uuid4()

    mp = ChatServerRequestProcessor(session, fake_redis)
    json_data = BasePayload.validate({
        'sender_id': str(default_user.id),
        'recipient_id': str(recipient.id),
        'payload': {
            'type': 'message',
            'timestamp': NOW.isoformat(),
            'message_id': str(message_id),
            'text': 'hello'
        }
    })
    await mp.process(json_data)

    chat: Chat = \
        chat_service.fetch_chat_by_members(recipient.id, default_user.id)
    assert len(chat.messages) == 1
    assert chat.messages[0].sender == default_user
    assert chat.initiator == default_user
    assert chat.the_other_person == recipient


@pytest.mark.anyio
async def test_set_received_status(
        default_user: models.User,
        chat_service: ChatService, user_service: UserService,
        fake_redis: aioredis.FakeRedis, session: Session,
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
    mp = ChatServerRequestProcessor(session, fake_redis)
    json_data = BasePayload.validate({
        'sender_id': str(default_user.id),
        'payload': {
            'type': 'message_status',
            'message_id': str(message_id),
            'status': 'received'
        }
    })
    await mp.process(json_data)

    chat = chat_service.fetch_chat(chat_id)
    assert len(chat.messages) == 1
    message: ChatMessage = chat_service.fetch_message(message_id)
    assert message.status == MessageStatus.RECEIVED


@pytest.mark.anyio
async def test_set_read_status(

        default_user: models.User,
        chat_service: ChatService, user_service: UserService,
        fake_redis: aioredis.FakeRedis, session: Session,
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
    mp = ChatServerRequestProcessor(session, fake_redis)
    json_data = BasePayload.validate({
        'sender_id': str(default_user.id),
        'payload': {
            'type': 'message_status',
            'message_id': str(message_id),
            'status': 'read'
        }
    })
    await mp.process(json_data)

    message: ChatMessage = chat_service.fetch_message(message_id)
    assert message.status == MessageStatus.READ


@pytest.mark.anyio
async def test_set_liked(

        default_user: models.User,
        chat_service: ChatService, user_service: UserService,
        fake_redis: aioredis.FakeRedis, session: Session,
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
    mp = ChatServerRequestProcessor(session, fake_redis)
    json_data = BasePayload.validate({
        'sender_id': str(default_user.id),
        'payload': {
            'type': 'like',
            'message_id': str(message_id),
            'like': True
        }
    })
    await mp.process(json_data)

    message: ChatMessage = chat_service.fetch_message(message_id)
    assert message.is_liked


@pytest.mark.anyio
async def test_set_disliked(
        default_user: models.User,
        chat_service: ChatService, user_service: UserService,
        fake_redis: aioredis.FakeRedis, session: Session,
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
    mp = ChatServerRequestProcessor(session, fake_redis)
    json_data = BasePayload.validate({
        'sender_id': str(default_user.id),
        'payload': {
            'type': 'like',
            'message_id': str(message_id),
            'like': False
        }
    })
    await mp.process(json_data)

    message: ChatMessage = chat_service.fetch_message(message_id)
    assert not message.is_liked


@pytest.mark.anyio
async def test_create_chat_direct(
        default_user: models.User,
        chat_service: ChatService, user_service: UserService,
        fake_redis: aioredis.FakeRedis, session: Session,
        redis_chats: RedisChatCacheService,
        randomizer: RandomEntityGenerator,
        default_user_auth_headers: dict[str, str]):
    recipient = randomizer.generate_random_user()
    chat_id = uuid.uuid4()
    mp = ChatServerRequestProcessor(session, fake_redis)

    default_user_id = str(default_user.id)
    recipient_id = str(recipient.id)

    json_data = BasePayload.validate({
        'sender_id': default_user_id,
        'recipient_id': recipient_id,
        'payload': {
            'type': 'create_chat',
            'source': ChatSource.DIRECT,
            'chat_id': str(chat_id),
            'message': {
                'message_id': str(uuid.uuid4()),
                'sender_id': default_user_id,
                'recipient_id': recipient_id,
                'timestamp': NOW.isoformat(),
                'text': 'hello'
            }
        }
    })
    await mp.process(json_data)

    chat: Chat = chat_service.fetch_chat(chat_id)
    # direct chats are created 'requested'
    assert chat.source == ChatSource.DIRECT
    assert chat.status == ChatStatus.REQUESTED
    assert chat.initiator_id == default_user.id
    assert chat.the_other_person_id == recipient.id
    assert len(chat.messages) == 1
    assert chat.messages[0].message == 'hello'

    assert await redis_chats.get_chat_partners(default_user_id) == {
        recipient_id}
    assert await redis_chats.get_chat_partners(recipient_id) == {
        default_user_id}


@pytest.mark.anyio
async def test_create_chat_text_lobby(
        default_user: models.User,
        chat_service: ChatService, user_service: UserService,
        fake_redis: aioredis.FakeRedis, session: Session,
        redis_chats: RedisChatCacheService,
        randomizer: RandomEntityGenerator,
        default_user_auth_headers: dict[str, str]):
    recipient = randomizer.generate_random_user()
    chat_id = uuid.uuid4()
    mp = ChatServerRequestProcessor(session, fake_redis)

    default_user_id = str(default_user.id)
    recipient_id = str(recipient.id)
    json_data = BasePayload.validate({
        'sender_id': default_user_id,
        'recipient_id': recipient_id,
        'payload': {
            'type': 'create_chat',
            'source': ChatSource.TEXT_LOBBY,
            'chat_id': str(chat_id),
            'messages': [{
                'message_id': str(uuid.uuid4()),
                'sender_id': default_user_id,
                'recipient_id': recipient_id,
                'timestamp': NOW.isoformat(),
                'text': 'hello'
            } for _ in range(5)]
        }
    })
    await mp.process(json_data)

    chat: Chat = chat_service.fetch_chat(chat_id)
    # lobby chats are accepted from the beginning
    assert chat.source == ChatSource.TEXT_LOBBY
    assert chat.status == ChatStatus.ACCEPTED
    assert chat.initiator_id == default_user.id
    assert chat.the_other_person_id == recipient.id
    assert len(chat.messages) == 5
    assert chat.messages[3].message == 'hello'

    assert await redis_chats.get_chat_partners(default_user_id) == {
        recipient_id}
    assert await redis_chats.get_chat_partners(recipient_id) == {
        default_user_id}


@pytest.mark.anyio
async def test_create_chat_audio_lobby(
        default_user: models.User,
        chat_service: ChatService, user_service: UserService,
        fake_redis: aioredis.FakeRedis, session: Session,
        redis_chats: RedisChatCacheService,
        randomizer: RandomEntityGenerator,
        default_user_auth_headers: dict[str, str]):
    recipient = randomizer.generate_random_user()
    chat_id = uuid.uuid4()
    mp = ChatServerRequestProcessor(session, fake_redis)

    default_user_id = str(default_user.id)
    recipient_id = str(recipient.id)
    json_data = BasePayload.validate({
        'sender_id': default_user_id,
        'recipient_id': recipient_id,
        'payload': {
            'type': 'create_chat',
            'source': ChatSource.VIDEO_LOBBY,
            'chat_id': str(chat_id),
        }
    })
    await mp.process(json_data)

    chat: Chat = chat_service.fetch_chat(chat_id)
    # lobby chats are accepted from the beginning
    assert chat.source == ChatSource.VIDEO_LOBBY
    assert chat.status == ChatStatus.ACCEPTED
    assert chat.initiator_id == default_user.id
    assert chat.the_other_person_id == recipient.id
    assert len(chat.messages) == 0

    assert await redis_chats.get_chat_partners(default_user_id) == {
        recipient_id}
    assert await redis_chats.get_chat_partners(recipient_id) == {
        default_user_id}


@pytest.mark.anyio
async def test_create_chat_video_lobby(
        default_user: models.User,
        chat_service: ChatService, user_service: UserService,
        fake_redis: aioredis.FakeRedis, session: Session,
        redis_chats: RedisChatCacheService,
        randomizer: RandomEntityGenerator,
        default_user_auth_headers: dict[str, str]):
    recipient = randomizer.generate_random_user()
    chat_id = uuid.uuid4()
    mp = ChatServerRequestProcessor(session, fake_redis)

    default_user_id = str(default_user.id)
    recipient_id = str(recipient.id)
    json_data = BasePayload.validate({
        'sender_id': default_user_id,
        'recipient_id': recipient_id,
        'payload': {
            'type': 'create_chat',
            'source': ChatSource.AUDIO_LOBBY,
            'chat_id': str(chat_id),
        }
    })
    await mp.process(json_data)

    chat: Chat = chat_service.fetch_chat(chat_id)
    # lobby chats are accepted from the beginning
    assert chat.source == ChatSource.AUDIO_LOBBY
    assert chat.status == ChatStatus.ACCEPTED
    assert chat.initiator_id == default_user.id
    assert chat.the_other_person_id == recipient.id
    assert len(chat.messages) == 0

    assert await redis_chats.get_chat_partners(default_user_id) == {
        recipient_id}
    assert await redis_chats.get_chat_partners(recipient_id) == {
        default_user_id}


@pytest.mark.anyio
async def test_decline_chat(
        default_user: models.User,
        chat_service: ChatService, user_service: UserService,
        fake_redis: aioredis.FakeRedis, session: Session,
        randomizer: RandomEntityGenerator,
        mocker: MockerFixture,
        redis_blacklist: RedisBlacklistService,
        redis_chats: RedisChatCacheService,
        default_user_auth_headers: dict[str, str]):
    mock_storage: MagicMock = \
        mocker.patch('swipe.swipe_server.chats.models.storage_client')

    recipient = randomizer.generate_random_user()
    chat_id = uuid.uuid4()
    initiator = randomizer.generate_random_user()
    chat = Chat(
        id=chat_id,
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

    default_user_id = str(default_user.id)
    recipient_id = str(recipient.id)

    await redis_chats.add_chat_partner(default_user_id, recipient_id)
    await redis_chats.add_chat_partner(recipient_id, default_user_id)

    mp = ChatServerRequestProcessor(session, fake_redis)
    json_data = BasePayload.validate({
        'sender_id': default_user_id,
        'recipient_id': recipient_id,
        'payload': {
            'type': 'decline_chat',
            'chat_id': str(chat_id),
        }
    })
    await mp.process(json_data)

    mock_storage.delete_chat_image.assert_called_with('345345.png')
    chat: Chat = chat_service.fetch_chat(chat_id)
    assert not chat

    session.refresh(default_user)
    session.refresh(recipient)

    assert len(default_user.blacklist) == 1
    assert recipient in default_user.blacklist
    assert default_user in recipient.blocked_by

    assert \
        await redis_blacklist.get_blacklist(default_user_id) == {recipient_id}
    assert \
        await redis_blacklist.get_blacklist(recipient_id) == {default_user_id}

    assert await redis_chats.get_chat_partners(default_user_id) == set()
    assert await redis_chats.get_chat_partners(recipient_id) == set()


@pytest.mark.anyio
async def test_accept_chat(
        default_user: models.User,
        chat_service: ChatService, user_service: UserService,
        fake_redis: aioredis.FakeRedis, session: Session,
        redis_chats: RedisChatCacheService,
        randomizer: RandomEntityGenerator,
        default_user_auth_headers: dict[str, str]):
    recipient = randomizer.generate_random_user()
    chat_id = uuid.uuid4()
    initiator = randomizer.generate_random_user()
    chat = Chat(
        id=chat_id,
        status=ChatStatus.OPENED, source=ChatSource.DIRECT,
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
    mp = ChatServerRequestProcessor(session, fake_redis)

    default_user_id = str(default_user.id)
    recipient_id = str(recipient.id)

    json_data = BasePayload.validate({
        'sender_id': default_user_id,
        'recipient_id': recipient_id,
        'payload': {
            'type': 'accept_chat',
            'chat_id': str(chat_id),
        }
    })
    await mp.process(json_data)

    chat: Chat = chat_service.fetch_chat(chat_id)
    assert chat.status == ChatStatus.ACCEPTED


@pytest.mark.anyio
async def test_open_chat(
        default_user: models.User,
        chat_service: ChatService, user_service: UserService,
        fake_redis: aioredis.FakeRedis,
        session: Session,
        randomizer: RandomEntityGenerator,
        default_user_auth_headers: dict[str, str]):
    recipient = randomizer.generate_random_user()
    chat_id = uuid.uuid4()
    initiator = randomizer.generate_random_user()
    chat = Chat(
        id=chat_id,
        status=ChatStatus.REQUESTED, source=ChatSource.DIRECT,
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
    mp = ChatServerRequestProcessor(session, fake_redis)
    json_data = BasePayload.validate({
        'sender_id': str(default_user.id),
        'recipient_id': str(recipient.id),
        'payload': {
            'type': 'open_chat',
            'chat_id': str(chat_id),
        }
    })
    await mp.process(json_data)

    chat: Chat = chat_service.fetch_chat(chat_id)
    assert chat.status == ChatStatus.OPENED
