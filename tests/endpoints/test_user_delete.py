import datetime
import uuid
from unittest.mock import MagicMock, call
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
from swipe.swipe_server.misc.errors import SwipeError
from swipe.swipe_server.misc.randomizer import RandomEntityGenerator
from swipe.swipe_server.users.enums import Gender
from swipe.swipe_server.users.models import AuthInfo, User
from swipe.swipe_server.users.schemas import OnlineFilterBody
from swipe.swipe_server.users.services.blacklist_service import BlacklistService
from swipe.swipe_server.users.services.online_cache import \
    RedisOnlineUserService
from swipe.swipe_server.users.services.popular_cache import PopularUserService, \
    CountryCacheService
from swipe.swipe_server.users.services.redis_services import \
    RedisBlacklistService, RedisUserCacheService
from swipe.swipe_server.users.services.user_service import UserService


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
        redis_user: RedisUserCacheService,
        redis_blacklist: RedisBlacklistService,
        default_user_auth_headers: dict[str, str]):
    default_user.gender = Gender.MALE

    mock_user_storage: MagicMock = \
        mocker.patch('swipe.swipe_server.users.models.storage_client')
    mock_events = \
        mocker.patch('swipe.swipe_server.users.endpoints.me.events')

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
    await redis_user.cache_user(default_user)

    await redis_blacklist.add_to_blacklist_cache(
        blocked_user_id=str(user_1.id), blocked_by_id=user_id)

    delete_image_calls = []
    for photo in photos:
        delete_image_calls.append(call(photo))
    delete_image_calls.append(call(default_user.avatar_id))

    old_country = default_user.location.country
    old_city = default_user.location.city
    old_gender = default_user.gender
    # -----------------------------------------------------
    await client.delete(
        f"{settings.API_V1_PREFIX}/me",
        params={
            'delete': True,
        },
        headers=default_user_auth_headers)

    mock_events.send_user_deleted_event.assert_called_with(str(default_user.id))

    mock_user_storage.delete_image.assert_has_calls(
        delete_image_calls, any_order=True)

    assert not await redis_user.get_user(str(default_user.id))
    assert not user_service.get_user(default_user.id)
    assert not session.execute(
        select(AuthInfo).where(AuthInfo.id == auth_info_id)). \
        scalars().one_or_none()

    all_settings = OnlineFilterBody(
        country=old_country, city=old_city, gender=old_gender
    )
    assert user_id not in await redis_online.get_online_users(
        default_user.age, all_settings)

    all_settings = OnlineFilterBody(country=old_country, gender=old_gender)
    assert user_id not in await redis_online.get_online_users(
        default_user.age, all_settings)

    all_settings = OnlineFilterBody(country=old_country, city=old_city, )
    assert user_id not in await redis_online.get_online_users(
        default_user.age, all_settings)

    all_settings = OnlineFilterBody(country=old_country)
    assert user_id not in await redis_online.get_online_users(
        default_user.age, all_settings)

    assert await redis_blacklist.get_blacklist(user_id) == set()


@pytest.mark.anyio
async def test_user_delete_with_chats(
        mocker: MockerFixture,
        client: AsyncClient,
        default_user: User,
        user_service: UserService,
        redis_user: RedisUserCacheService,
        randomizer: RandomEntityGenerator,
        session: Session,
        default_user_auth_headers: dict[str, str]):
    mock_user_storage: MagicMock = \
        mocker.patch('swipe.swipe_server.users.models.storage_client')
    mock_chat_storage: MagicMock = \
        mocker.patch('swipe.swipe_server.chats.models.storage_client')
    mock_requests = mocker.patch('swipe.swipe_server.events.requests')

    other_user = randomizer.generate_random_user()
    photos: list[str] = default_user.photos
    chat_id = uuid.uuid4()
    chat = Chat(
        id=chat_id, creation_date=datetime.datetime.utcnow(),
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

    await redis_user.cache_user(default_user)

    auth_info_id: UUID = default_user.auth_info.id
    # ---------------------------------------------------------------------
    await client.delete(
        f"{settings.API_V1_PREFIX}/me",
        params={
            'delete': True,
        },
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
        'user_id': str(default_user.id)
    })

    assert not await redis_user.get_user(str(default_user.id))
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
        redis_user: RedisUserCacheService,
        randomizer: RandomEntityGenerator,
        session: Session,
        default_user_auth_headers: dict[str, str]):
    mock_user_storage: MagicMock = \
        mocker.patch('swipe.swipe_server.users.models.storage_client')
    mock_events = mocker.patch('swipe.swipe_server.users.endpoints.me.events')

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

    await redis_user.cache_user(default_user)

    auth_info_id: UUID = default_user.auth_info.id
    await client.delete(
        f"{settings.API_V1_PREFIX}/me",
        params={
            'delete': True,
        },
        headers=default_user_auth_headers)

    calls = []
    for photo in photos:
        calls.append(call(photo))
    calls.append(call(default_user.avatar_id))
    mock_user_storage.delete_image.assert_has_calls(
        calls, any_order=True)

    mock_events.send_user_deleted_event.assert_called_with(str(default_user.id))

    assert not await redis_user.get_user(str(default_user.id))
    assert not user_service.get_user(default_user.id)
    assert not session.execute(
        select(AuthInfo).where(AuthInfo.id == auth_info_id)). \
        scalars().one_or_none()

    assert set(session.execute(select(GlobalChatMessage.id)).scalars()) \
           == {msg3.id, msg4.id}


@pytest.mark.anyio
async def test_user_delete_with_global_deactivate(
        mocker: MockerFixture,
        client: AsyncClient,
        default_user: User,
        user_service: UserService,
        redis_user: RedisUserCacheService,
        randomizer: RandomEntityGenerator,
        session: Session,
        default_user_auth_headers: dict[str, str]):
    mock_user_storage: MagicMock = \
        mocker.patch('swipe.swipe_server.users.models.storage_client')
    mock_events = mocker.patch('swipe.swipe_server.users.endpoints.me.events')

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

    await redis_user.cache_user(default_user)

    auth_info_id: UUID = default_user.auth_info.id
    await client.delete(
        f"{settings.API_V1_PREFIX}/me",
        params={
            'delete': False,
        },
        headers=default_user_auth_headers)

    # photos remain in storage
    mock_user_storage.delete_image.assert_not_called()

    mock_events.send_user_deleted_event.assert_called_with(str(default_user.id))

    with pytest.raises(SwipeError) as exc_info:
        assert user_service.get_user(default_user.id)
    assert 'is deactivated' in str(exc_info.value)

    # still gone from cache
    assert not await redis_user.get_user(str(default_user.id))
    assert session.execute(
        select(User.deactivation_date).where(User.id == default_user.id)
    ).scalars().one_or_none() is not None
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
        redis_user: RedisUserCacheService,
        blacklist_service: BlacklistService,
        redis_blacklist: RedisBlacklistService,
        randomizer: RandomEntityGenerator,
        session: Session,
        default_user_auth_headers: dict[str, str]):
    mocker.patch('swipe.swipe_server.users.models.storage_client')
    mock_events = mocker.patch('swipe.swipe_server.users.endpoints.me.events')

    other_user = randomizer.generate_random_user()
    await blacklist_service.update_blacklist(
        str(other_user.id), str(default_user.id))
    session.commit()

    await redis_user.cache_user(default_user)

    auth_info_id: UUID = default_user.auth_info.id
    await client.delete(
        f"{settings.API_V1_PREFIX}/me",
        params={
            'delete': True,
        },
        headers=default_user_auth_headers)

    mock_events.send_user_deleted_event.assert_called_with(str(default_user.id))

    assert not await redis_user.get_user(str(default_user.id))
    assert not user_service.get_user(default_user.id)
    assert not session.execute(
        select(AuthInfo).where(AuthInfo.id == auth_info_id)). \
        scalars().one_or_none()

    session.refresh(other_user)
    assert len(other_user.blacklist) == 0

    # user is gone and so is his blacklist cache
    assert await redis_blacklist.get_blacklist(str(default_user.id)) == set()
