import datetime
import random
import uuid

import lorem
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from swipe.chats.models import Chat, ChatStatus, GlobalChatMessage, ChatMessage, \
    MessageStatus, ChatSource
from swipe.chats.services import ChatService
from swipe.errors import SwipeError
from swipe.randomizer import RandomEntityGenerator
from swipe.users import models


@pytest.mark.anyio
async def test_create_chat(
        default_user: models.User,
        session: Session,
        randomizer: RandomEntityGenerator,
        chat_service: ChatService):
    user_1 = randomizer.generate_random_user()
    user_2 = randomizer.generate_random_user()
    chat_id = uuid.uuid4()
    chat_service.create_chat(
        chat_id=chat_id, initiator_id=user_1.id, the_other_person_id=user_2.id,
        chat_status=ChatStatus.ACCEPTED, source=ChatSource.VIDEO_LOBBY)

    chat = session.execute(
        select(Chat).where(Chat.id == chat_id)).scalars().one()
    assert chat.id == chat_id


@pytest.mark.anyio
async def test_create_chat_duplicate(
        default_user: models.User,
        session: Session,
        randomizer: RandomEntityGenerator,
        chat_service: ChatService):
    user_1 = randomizer.generate_random_user()
    user_2 = randomizer.generate_random_user()
    chat_id = uuid.uuid4()
    chat_service.create_chat(
        chat_id=chat_id, initiator_id=user_1.id, the_other_person_id=user_2.id,
        chat_status=ChatStatus.ACCEPTED, source=ChatSource.VIDEO_LOBBY)

    chat = session.execute(
        select(Chat).where(Chat.id == chat_id)).scalars().one()
    assert chat.id == chat_id

    with pytest.raises(SwipeError):
        chat_service.create_chat(
            chat_id=chat_id, initiator_id=user_1, the_other_person_id=user_2,
            chat_status=ChatStatus.ACCEPTED, source=ChatSource.VIDEO_LOBBY)


@pytest.mark.anyio
async def test_fetch_chat_by_members(
        default_user: models.User,
        session: Session,
        randomizer: RandomEntityGenerator,
        chat_service: ChatService):
    user_1 = randomizer.generate_random_user()
    user_2 = randomizer.generate_random_user()
    user_3 = randomizer.generate_random_user()

    new_chat = randomizer.generate_random_chat(user_1, user_2)

    result_chat = chat_service.fetch_chat_by_members(user_1.id, user_2.id)
    assert result_chat is not None
    assert result_chat.id == new_chat.id

    result_chat = chat_service.fetch_chat_by_members(user_2.id, user_1.id)
    assert result_chat is not None
    assert result_chat.id == new_chat.id

    result_chat = chat_service.fetch_chat_by_members(user_1.id, user_3.id)
    assert result_chat is None


@pytest.mark.anyio
async def test_post_message_chat_exists(
        default_user: models.User,
        session: Session,
        randomizer: RandomEntityGenerator,
        chat_service: ChatService):
    user_1 = randomizer.generate_random_user()
    user_2 = randomizer.generate_random_user()

    chat = Chat(status=ChatStatus.ACCEPTED, source=ChatSource.VIDEO_LOBBY,
                initiator=user_1, the_other_person=user_2)
    session.add(chat)
    session.commit()
    session.refresh(chat)

    chat_service.post_message(
        message_id=uuid.uuid4(), sender_id=user_2.id, recipient_id=user_1.id,
        timestamp=datetime.datetime.now(), message='hello')

    chat = chat_service.fetch_chat(chat.id)
    assert len(chat.messages) == 1
    assert chat.messages[0].message == 'hello'


@pytest.mark.anyio
async def test_post_message_no_chat(
        default_user: models.User,
        session: Session,
        randomizer: RandomEntityGenerator,
        chat_service: ChatService):
    user_1 = randomizer.generate_random_user()
    user_2 = randomizer.generate_random_user()

    with pytest.raises(SwipeError):
        chat_service.post_message(
            message_id=uuid.uuid4(), sender_id=user_2.id,
            recipient_id=user_1.id,
            timestamp=datetime.datetime.now(), message='hello')


@pytest.mark.anyio
async def test_post_message_to_global(
        default_user: models.User,
        session: Session,
        randomizer: RandomEntityGenerator,
        chat_service: ChatService):
    user_1 = randomizer.generate_random_user()

    chat_service.post_message_to_global(
        message_id=(first_message_id := uuid.uuid4()),
        sender_id=default_user.id,
        timestamp=datetime.datetime.now(), message='hello')
    chat_service.post_message_to_global(
        message_id=(second_message_id := uuid.uuid4()), sender_id=user_1.id,
        timestamp=datetime.datetime.now() + datetime.timedelta(minutes=10),
        message='hello again')

    global_messages: list[GlobalChatMessage] = chat_service.fetch_global_chat()
    assert len(global_messages) == 2
    assert global_messages[0].id == second_message_id
    assert global_messages[1].id == first_message_id


@pytest.mark.anyio
async def test_fetch_from_global_from_id(
        default_user: models.User,
        session: Session,
        randomizer: RandomEntityGenerator,
        chat_service: ChatService):
    user_1 = randomizer.generate_random_user()

    chat_service.post_message_to_global(
        message_id=(first_message_id := uuid.uuid4()),
        sender_id=default_user.id,
        timestamp=datetime.datetime.now(), message='hello')
    chat_service.post_message_to_global(
        message_id=(second_message_id := uuid.uuid4()), sender_id=user_1.id,
        timestamp=datetime.datetime.now() + datetime.timedelta(minutes=10),
        message='hello again')
    chat_service.post_message_to_global(
        message_id=(third_message_id := uuid.uuid4()), sender_id=user_1.id,
        timestamp=datetime.datetime.now() + datetime.timedelta(minutes=20),
        message='hello again again')

    global_messages: list[GlobalChatMessage] = \
        chat_service.fetch_global_chat(first_message_id)
    assert len(global_messages) == 2
    assert global_messages[0].id == third_message_id
    assert global_messages[1].id == second_message_id


@pytest.mark.anyio
async def test_set_received(
        default_user: models.User,
        session: Session,
        randomizer: RandomEntityGenerator,
        chat_service: ChatService):
    user_1 = randomizer.generate_random_user()
    chat: Chat = randomizer.generate_random_chat(
        default_user, user_1, n_messages=3)

    message_id = chat.messages[2].id

    chat_service.set_received_status(message_id)
    new_status = session.execute(
        select(ChatMessage.status).where(
            ChatMessage.id == message_id)).scalars().one()
    assert new_status == MessageStatus.RECEIVED


@pytest.mark.anyio
async def test_set_read(
        default_user: models.User,
        session: Session,
        randomizer: RandomEntityGenerator,
        chat_service: ChatService):
    user_1 = randomizer.generate_random_user()
    chat = Chat(status=ChatStatus.ACCEPTED, source=ChatSource.VIDEO_LOBBY,
                initiator=user_1, the_other_person=default_user)
    session.add(chat)

    message_time = datetime.datetime.now()
    earliest_message = ChatMessage(
        timestamp=message_time, status=MessageStatus.SENT,
        message=lorem.sentence(), sender=user_1)
    chat.messages.append(earliest_message)

    message_time -= datetime.timedelta(minutes=random.randint(1, 10))
    second_message = ChatMessage(
        timestamp=message_time, status=MessageStatus.RECEIVED,
        message=lorem.sentence(), sender=user_1)
    chat.messages.append(second_message)

    message_time -= datetime.timedelta(minutes=random.randint(1, 10))
    third_message = ChatMessage(
        timestamp=message_time, status=MessageStatus.READ,
        message=lorem.sentence(), sender=default_user)
    chat.messages.append(third_message)
    session.commit()

    # both earliest and second message statuses must be updated
    chat_service.set_read_status(earliest_message.id)
    new_status = session.execute(
        select(ChatMessage.status).where(
            ChatMessage.id == earliest_message.id)).scalars().one()
    assert new_status == MessageStatus.READ

    new_status = session.execute(
        select(ChatMessage.status).where(
            ChatMessage.id == second_message.id)).scalars().one()
    assert new_status == MessageStatus.READ


@pytest.mark.anyio
async def test_set_like(
        default_user: models.User,
        session: Session,
        randomizer: RandomEntityGenerator,
        chat_service: ChatService):
    user_1 = randomizer.generate_random_user()
    chat = Chat(status=ChatStatus.ACCEPTED, source=ChatSource.VIDEO_LOBBY,
                initiator=user_1, the_other_person=default_user)
    session.add(chat)

    message = ChatMessage(
        timestamp=datetime.datetime.now(), status=MessageStatus.SENT,
        message=lorem.sentence(), sender=user_1, is_liked=False)
    chat.messages.append(message)
    session.commit()

    chat_service.set_like_status(message.id, True)
    new_like_status = session.execute(
        select(ChatMessage.is_liked).where(
            ChatMessage.id == message.id)).scalars().one()
    assert new_like_status is True

    chat_service.set_like_status(message.id, False)
    new_like_status = session.execute(
        select(ChatMessage.is_liked).where(
            ChatMessage.id == message.id)).scalars().one()
    assert new_like_status is False
