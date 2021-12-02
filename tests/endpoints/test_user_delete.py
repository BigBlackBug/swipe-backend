import datetime
import uuid
from unittest.mock import MagicMock, call, ANY
from uuid import UUID

import aioredis
import pytest
from httpx import AsyncClient
from pytest_mock import MockerFixture
from sqlalchemy import select
from sqlalchemy.orm import Session

from swipe.settings import settings
from swipe.swipe_server.chats.models import ChatMessage, MessageStatus, Chat, \
    ChatStatus, \
    ChatSource, GlobalChatMessage
from swipe.swipe_server.misc.randomizer import RandomEntityGenerator
from swipe.swipe_server.users.enums import Gender
from swipe.swipe_server.users.models import AuthInfo, User
from swipe.swipe_server.users.redis_services import RedisBlacklistService, \
    RedisOnlineUserService, RedisPopularService, OnlineUserCacheParams
from swipe.swipe_server.users.services import UserService, BlacklistService, \
    PopularUserService, CountryCacheService


@pytest.mark.anyio
async def test_user_delete(
        mocker: MockerFixture,
        client: AsyncClient,
        default_user: User,
        randomizer: RandomEntityGenerator,
        user_service: UserService,
        session: Session,
        fake_redis: aioredis.Redis,
        redis_online: RedisOnlineUserService,
        redis_blacklist: RedisBlacklistService,
        default_user_auth_headers: dict[str, str]):
    default_user.gender = Gender.MALE

    mock_user_storage: MagicMock = \
        mocker.patch('swipe.swipe_server.users.models.storage_client')
    mock_requests = \
        mocker.patch('swipe.swipe_server.users.endpoints.me.requests')

    user_1 = randomizer.generate_random_user()
    auth_info_id: UUID = default_user.auth_info.id
    photos: list[str] = default_user.photos

    user_id = str(default_user.id)
    await redis_online.add_to_online_caches(default_user)
    # populating caches
    cache_service = CountryCacheService(session, fake_redis)
    await cache_service.populate_country_cache()
    popular_service = PopularUserService(session, fake_redis)
    await popular_service.populate_popular_cache()

    await redis_blacklist.add_to_blacklist_cache(
        blocked_user_id=str(user_1.id), blocked_by_id=user_id)

    delete_image_calls = []
    for photo in photos:
        delete_image_calls.append(call(photo))
    delete_image_calls.append(call(default_user.avatar_id))

    # -----------------------------------------------------
    await client.delete(
        f"{settings.API_V1_PREFIX}/me",
        headers=default_user_auth_headers)

    # no chats -> no event
    url = f'{settings.CHAT_SERVER_HOST}/events/user_deleted'
    assert not mock_requests.post.call_args_list
    assert call(url, json=ANY) not in mock_requests.post.call_args_list

    mock_user_storage.delete_image.assert_has_calls(
        delete_image_calls, any_order=True)

    assert not user_service.get_user(default_user.id)
    assert not session.execute(
        select(AuthInfo).where(AuthInfo.id == auth_info_id)). \
        scalars().one_or_none()

    assert not await redis_online.is_online(
        str(default_user.id), default_user.age)

    all_settings = OnlineUserCacheParams(
        age=default_user.age,
        country=default_user.location.country,
        city=default_user.location.city,
        gender=default_user.gender
    )
    assert user_id not in await redis_online.get_online_users(all_settings)

    all_settings = OnlineUserCacheParams(
        age=default_user.age,
        country=default_user.location.country,
        gender=default_user.gender
    )
    assert user_id not in await redis_online.get_online_users(all_settings)

    all_settings = OnlineUserCacheParams(
        age=default_user.age,
        country=default_user.location.country,
        city=default_user.location.city,
    )
    assert user_id not in await redis_online.get_online_users(all_settings)

    all_settings = OnlineUserCacheParams(
        age=default_user.age,
        country=default_user.location.country,
    )
    assert user_id not in await redis_online.get_online_users(all_settings)

    assert await redis_blacklist.get_blacklist(user_id) == set()


@pytest.mark.anyio
async def test_user_delete_with_chats(
        mocker: MockerFixture,
        client: AsyncClient,
        default_user: User,
        user_service: UserService,
        randomizer: RandomEntityGenerator,
        session: Session,
        default_user_auth_headers: dict[str, str]):
    mock_user_storage: MagicMock = \
        mocker.patch('swipe.swipe_server.users.models.storage_client')
    mock_chat_storage: MagicMock = \
        mocker.patch('swipe.swipe_server.chats.models.storage_client')
    mock_requests = \
        mocker.patch('swipe.swipe_server.users.endpoints.me.requests')

    other_user = randomizer.generate_random_user()
    photos: list[str] = default_user.photos
    chat_id = uuid.uuid4()
    chat = Chat(
        id=chat_id,
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
    session.commit()

    auth_info_id: UUID = default_user.auth_info.id
    # ---------------------------------------------------------------------
    await client.delete(
        f"{settings.API_V1_PREFIX}/me",
        headers=default_user_auth_headers)
    # --------------------------------------------------------------------

    calls = []
    for photo in photos:
        calls.append(call(photo))
    calls.append(call(default_user.avatar_id))
    mock_user_storage.delete_image.assert_has_calls(
        calls, any_order=True)

    mock_chat_storage.delete_chat_image.assert_called_with('345345.png')

    url = f'{settings.CHAT_SERVER_HOST}/events/user_deleted'
    mock_requests.post.assert_called_with(url, json={
        'user_id': str(default_user.id),
        'recipients': [str(other_user.id),]
    })

    assert not user_service.get_user(default_user.id)
    assert not session.execute(
        select(AuthInfo).where(AuthInfo.id == auth_info_id)). \
        scalars().one_or_none()

    assert session.query(Chat).count() == 0
    assert session.query(ChatMessage).count() == 0

    assert session.execute(
        select(User).where(User.id == other_user.id)).scalars().one()


@pytest.mark.anyio
async def test_user_delete_with_global(
        mocker: MockerFixture,
        client: AsyncClient,
        default_user: User,
        user_service: UserService,
        randomizer: RandomEntityGenerator,
        session: Session,
        default_user_auth_headers: dict[str, str]):
    mock_user_storage: MagicMock = \
        mocker.patch('swipe.swipe_server.users.models.storage_client')

    photos: list[str] = default_user.photos
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

    auth_info_id: UUID = default_user.auth_info.id
    await client.delete(
        f"{settings.API_V1_PREFIX}/me",
        headers=default_user_auth_headers)

    calls = []
    for photo in photos:
        calls.append(call(photo))
    calls.append(call(default_user.avatar_id))
    mock_user_storage.delete_image.assert_has_calls(
        calls, any_order=True)

    assert not user_service.get_user(default_user.id)
    assert not session.execute(
        select(AuthInfo).where(AuthInfo.id == auth_info_id)). \
        scalars().one_or_none()

    assert set(session.execute(select(GlobalChatMessage.id)).scalars()) \
           == {msg3.id, msg4.id}


@pytest.mark.anyio
async def test_user_delete_with_blacklist(
        mocker: MockerFixture,
        client: AsyncClient,
        default_user: User,
        user_service: UserService,
        blacklist_service: BlacklistService,
        redis_blacklist: RedisBlacklistService,
        randomizer: RandomEntityGenerator,
        session: Session,
        default_user_auth_headers: dict[str, str]):
    mocker.patch('swipe.swipe_server.users.models.storage_client')

    other_user = randomizer.generate_random_user()
    await blacklist_service.update_blacklist(
        str(other_user.id), str(default_user.id))
    session.commit()

    auth_info_id: UUID = default_user.auth_info.id
    await client.delete(
        f"{settings.API_V1_PREFIX}/me",
        headers=default_user_auth_headers)

    assert not user_service.get_user(default_user.id)
    assert not session.execute(
        select(AuthInfo).where(AuthInfo.id == auth_info_id)). \
        scalars().one_or_none()

    session.refresh(other_user)
    assert len(other_user.blacklist) == 0

    # user is gone and so is his blacklist cache
    assert await redis_blacklist.get_blacklist(str(default_user.id)) == set()
