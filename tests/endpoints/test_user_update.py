import datetime
import io
import uuid
from unittest import mock
from unittest.mock import MagicMock

import dateutil.parser
import pytest
from PIL import Image
from dateutil.relativedelta import relativedelta
from httpx import AsyncClient, Response
from pytest_mock import MockerFixture
from sqlalchemy.orm import Session

from swipe.settings import settings
from swipe.swipe_server.users.enums import ZodiacSign, Gender
from swipe.swipe_server.users.models import User
from swipe.swipe_server.users.services import UserService, RedisUserService, \
    OnlineUserRequestCacheParams


@pytest.mark.anyio
async def test_user_update_dob_zodiac(
        client: AsyncClient,
        default_user: User,
        user_service: UserService,
        redis_service: RedisUserService,
        session: Session,
        default_user_auth_headers: dict[str, str]):
    default_user.date_of_birth = datetime.date.today()
    default_user.zodiac_sign = None
    session.commit()
    response: Response = await client.patch(
        f"{settings.API_V1_PREFIX}/me",
        headers=default_user_auth_headers,
        json={
            'date_of_birth': '2020-02-01'
        })
    assert default_user.zodiac_sign == ZodiacSign.from_date('2020-02-01')
    assert default_user.date_of_birth == \
           dateutil.parser.parse('2020-02-01').date()


@pytest.mark.anyio
async def test_user_update_location(
        client: AsyncClient,
        default_user: User,
        user_service: UserService,
        redis_service: RedisUserService,
        session: Session,
        default_user_auth_headers: dict[str, str]):
    default_user.gender = Gender.MALE
    session.commit()

    await redis_service.connect_user(user_id=default_user.id)

    age_delta = relativedelta(datetime.date.today(),
                              default_user.date_of_birth)
    age = round(age_delta.years + age_delta.months / 12)

    # assuming some other users are in the cache for Hello
    cached_user_id = str(uuid.uuid4())
    cache_settings = OnlineUserRequestCacheParams(
        age=age,
        age_diff=4,
        current_country='What Country',
        gender_filter=default_user.gender,
        city_filter='Hello'
    )
    # assuming some other users are in the cache for Hello
    await redis_service.store_user_ids(cache_settings, {cached_user_id, })

    cache_settings_country = OnlineUserRequestCacheParams(
        age=age,
        age_diff=4,
        current_country='What Country',
        gender_filter=default_user.gender,
    )

    await redis_service.store_user_ids(cache_settings_country,
                                       {cached_user_id, })
    # save to online user cache
    response: Response = await client.patch(
        f"{settings.API_V1_PREFIX}/me",
        headers=default_user_auth_headers,
        json={
            'location': {
                'city': 'Hello',
                'country': 'What Country',
                'flag': 'f'
            }
        })
    session.refresh(default_user)
    assert default_user.location.city == 'Hello'
    assert default_user.location.country == 'What Country'

    # assert country is saved to cache
    country_keys = await redis_service.redis.keys("country:*")
    assert 'country:What Country' in country_keys
    cities = await redis_service.redis.lrange('country:What Country', 0, -1)
    assert 'Hello' in cities

    # user is added to current caches
    assert await redis_service.find_user_ids(cache_settings) == {
        str(default_user.id), cached_user_id}
    assert await redis_service.find_user_ids(cache_settings_country) == {
        str(default_user.id), cached_user_id}


@pytest.mark.anyio
async def test_user_update_photo_list(
        mocker: MockerFixture,
        client: AsyncClient,
        default_user: User,
        user_service: UserService,
        redis_service: RedisUserService,
        session: Session,
        default_user_auth_headers: dict[str, str]):
    default_user.photos = ['photo_1.png', 'photo_2.png']
    session.commit()

    old_avatar_id = default_user.avatar_id
    mock_storage: MagicMock = \
        mocker.patch('swipe.swipe_server.users.services.storage_client')
    update_avatar_mock = MagicMock()
    mocker.patch('swipe.swipe_server.users.services.UserService._update_avatar',
                 update_avatar_mock)
    # patch
    response: Response = await client.patch(
        f"{settings.API_V1_PREFIX}/me",
        headers=default_user_auth_headers,
        json={
            'photos': ['photo_2.png', 'photo_1.png']
        })
    assert response.status_code == 200
    update_avatar_mock.assert_called_with(default_user, photo_id='photo_2.png')
    mock_storage.delete_image.assert_called_with(old_avatar_id)


@pytest.mark.anyio
async def test_user_add_first_photo(
        mocker: MockerFixture,
        random_image: Image,
        client: AsyncClient,
        default_user: User,
        user_service: UserService,
        redis_service: RedisUserService,
        session: Session,
        default_user_auth_headers: dict[str, str]):
    default_user.photos = []
    session.commit()

    update_avatar_mock = MagicMock()
    mocker.patch('swipe.swipe_server.users.services.UserService._update_avatar',
                 update_avatar_mock)
    mock_storage: MagicMock = \
        mocker.patch('swipe.swipe_server.users.services.storage_client')

    image_data = io.BytesIO()
    random_image.save(image_data, format='png')

    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/me/photos",
        headers=default_user_auth_headers,
        files={
            'file': ('photo.png', image_data.getvalue(), 'image/png')
        })

    assert response.status_code == 201
    mock_storage.upload_image.assert_called()
    update_avatar_mock.assert_called_with(
        default_user, image_content=mock.ANY)


@pytest.mark.anyio
async def test_user_delete_photo(
        mocker: MockerFixture,
        random_image: Image,
        client: AsyncClient,
        default_user: User,
        user_service: UserService,
        redis_service: RedisUserService,
        session: Session,
        default_user_auth_headers: dict[str, str]):
    default_user.photos = ['photo_1.png', 'photo_2.png']
    session.commit()

    update_avatar_mock = MagicMock()
    mocker.patch('swipe.swipe_server.users.services.UserService._update_avatar',
                 update_avatar_mock)
    mock_storage: MagicMock = mocker.patch(
        'swipe.swipe_server.users.services.storage_client')

    image_data = io.BytesIO()
    random_image.save(image_data, format='png')

    response: Response = await client.delete(
        f"{settings.API_V1_PREFIX}/me/photos/photo_1.png",
        headers=default_user_auth_headers)

    assert response.status_code == 204
    update_avatar_mock.assert_called_with(default_user, photo_id='photo_2.png')
    mock_storage.delete_image.assert_called_with('photo_1.png')
