import datetime

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.orm import Session

from settings import settings
from swipe.users import models
from swipe.users.enums import Gender
from swipe.users.services import UserService, RedisService


@pytest.mark.anyio
async def test_user_fetch_offline_ignore(
        client: AsyncClient,
        default_user: models.User,
        user_service: UserService,
        session: Session,
        default_user_auth_headers: dict[str, str]):
    default_user.date_of_birth = datetime.date.today().replace(year=2000)

    # --------------------------------------------------------------------------
    user_1 = user_service.generate_random_user()
    user_1.date_of_birth = datetime.date.today().replace(year=2000)
    user_1.location.country = 'Russia'

    user_2 = user_service.generate_random_user()
    user_2.date_of_birth = datetime.date.today().replace(year=2000)
    user_2.location.country = 'Russia'

    user_3 = user_service.generate_random_user()
    user_3.date_of_birth = datetime.date.today().replace(year=2001)
    user_3.location.country = 'Russia'

    user_4 = user_service.generate_random_user()
    user_4.date_of_birth = datetime.date.today().replace(year=2005)
    user_4.location.country = 'Russia'
    session.commit()
    # --------------------------------------------------------------------------

    # ignore+offline+all genders+whole country
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch",
        headers=default_user_auth_headers,
        json={
            'online': False,
            'limit': 10,
            'ignore_users': [str(user_4.id), ]
        }
    )

    assert response.status_code == 200
    resp_data = response.json()
    assert {user['id'] for user in resp_data} == {str(user_1.id),
                                                  str(user_2.id),
                                                  str(user_3.id)}


@pytest.mark.anyio
async def test_user_fetch_offline_limit_sort_age(
        client: AsyncClient,
        default_user: models.User,
        user_service: UserService,
        session: Session,
        default_user_auth_headers: dict[str, str]):
    default_user.date_of_birth = datetime.date.today().replace(year=2000)

    # --------------------------------------------------------------------------
    user_1 = user_service.generate_random_user()
    user_1.date_of_birth = datetime.date.today().replace(year=2000)
    user_1.location.country = 'Russia'

    user_2 = user_service.generate_random_user()
    user_2.date_of_birth = datetime.date.today().replace(year=2000)
    user_2.location.country = 'Russia'

    user_3 = user_service.generate_random_user()
    user_3.date_of_birth = datetime.date.today().replace(year=2001)
    user_3.location.country = 'Russia'

    user_4 = user_service.generate_random_user()
    user_4.date_of_birth = datetime.date.today().replace(year=2005)
    user_4.location.country = 'Russia'
    session.commit()
    # --------------------------------------------------------------------------

    # ignore+offline+all genders+whole country+small limit
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch",
        headers=default_user_auth_headers,
        json={
            'online': False,
            'limit': 3,
            'sort': 'age_diff'
        }
    )

    assert response.status_code == 200
    resp_data = response.json()
    assert len(resp_data) == 3
    assert resp_data[0]['id'] == str(user_1.id)
    assert resp_data[1]['id'] == str(user_2.id)
    assert resp_data[2]['id'] == str(user_3.id)


@pytest.mark.anyio
async def test_user_fetch_online_gender(
        client: AsyncClient,
        default_user: models.User,
        user_service: UserService,
        redis_service: RedisService,
        session: Session,
        default_user_auth_headers: dict[str, str]):
    default_user.date_of_birth = datetime.date.today().replace(year=2000)

    # --------------------------------------------------------------------------
    user_1 = user_service.generate_random_user()
    user_1.name = 'user1'
    user_1.date_of_birth = datetime.date.today().replace(year=2000)
    user_1.gender = Gender.FEMALE
    user_1.location.country = 'Russia'

    user_2 = user_service.generate_random_user()
    user_2.name = 'user2'
    user_2.date_of_birth = datetime.date.today().replace(year=2000)
    user_2.gender = Gender.FEMALE
    user_2.location.country = 'Russia'

    user_3 = user_service.generate_random_user()
    user_3.name = 'user3'
    user_3.date_of_birth = datetime.date.today().replace(year=2001)
    user_3.gender = Gender.MALE
    await redis_service.refresh_online_status(user_3)
    user_3.location.country = 'Russia'

    user_4 = user_service.generate_random_user()
    user_4.name = 'user4'
    user_4.date_of_birth = datetime.date.today().replace(year=2005)
    user_4.gender = Gender.MALE
    user_4.location.country = 'Russia'

    user_5 = user_service.generate_random_user()
    user_5.name = 'user5'
    user_5.date_of_birth = datetime.date.today().replace(year=2002)
    user_5.gender = Gender.ATTACK_HELICOPTER
    user_5.location.country = 'Russia'
    session.commit()
    # --------------------------------------------------------------------------

    # online+gender
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch",
        headers=default_user_auth_headers,
        json={
            'online': True,
            'gender': 'male'
        }
    )

    assert response.status_code == 200
    resp_data = response.json()
    assert {user['id'] for user in resp_data} == {str(user_3.id)}


@pytest.mark.anyio
async def test_user_fetch_online_city(
        client: AsyncClient,
        default_user: models.User,
        user_service: UserService,
        redis_service: RedisService,
        session: Session,
        default_user_auth_headers: dict[str, str]):
    default_user.date_of_birth = datetime.date.today().replace(year=2000)

    # --------------------------------------------------------------------------
    user_1 = user_service.generate_random_user()
    user_1.name = 'user1'
    user_1.date_of_birth = datetime.date.today().replace(year=2000)
    user_1.gender = Gender.FEMALE
    user_1.set_location({
        'country': 'Russia', 'city': 'Moscow', 'flag': 'F'
    })

    user_2 = user_service.generate_random_user()
    user_2.name = 'user2'
    user_2.date_of_birth = datetime.date.today().replace(year=2000)
    user_2.gender = Gender.FEMALE
    user_2.set_location({
        'country': 'Russia', 'city': 'Moscow', 'flag': 'F'
    })

    user_3 = user_service.generate_random_user()
    user_3.name = 'user3'
    user_3.date_of_birth = datetime.date.today().replace(year=2001)
    user_3.gender = Gender.MALE
    await redis_service.refresh_online_status(user_3, ttl=60 * 60)
    user_3.set_location({
        'country': 'Russia', 'city': 'Saint Petersburg', 'flag': 'F'
    })

    user_4 = user_service.generate_random_user()
    user_4.name = 'user4'
    user_4.date_of_birth = datetime.date.today().replace(year=2005)
    await redis_service.refresh_online_status(user_4, ttl=60 * 60)
    user_4.gender = Gender.MALE
    user_4.set_location({
        'country': 'Russia', 'city': 'Saint Petersburg', 'flag': 'F'
    })

    user_5 = user_service.generate_random_user()
    user_5.name = 'user5'
    user_5.date_of_birth = datetime.date.today().replace(year=2002)
    user_5.gender = Gender.ATTACK_HELICOPTER
    user_5.set_location({
        'country': 'Russia', 'city': 'Saint Petersburg', 'flag': 'F'
    })
    session.commit()
    # --------------------------------------------------------------------------

    # online+city
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch",
        headers=default_user_auth_headers,
        json={
            'online': True,
            'city': 'Saint Petersburg'
        }
    )

    assert response.status_code == 200
    resp_data = response.json()
    assert {user['id'] for user in resp_data} == {str(user_3.id),
                                                  str(user_4.id)}
