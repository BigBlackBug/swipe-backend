import datetime

import aioredis
import pytest
from httpx import AsyncClient, Response
from sqlalchemy.orm import Session

from swipe.settings import settings
from swipe.swipe_server.misc.randomizer import RandomEntityGenerator
from swipe.swipe_server.users.enums import Gender
from swipe.swipe_server.users.models import User
from swipe.swipe_server.users.services.online_cache import \
    RedisOnlineUserService
from swipe.swipe_server.users.services.services import UserService, \
    PopularUserService, CountryCacheService


@pytest.mark.anyio
async def test_user_fetch_popular(
        client: AsyncClient,
        default_user: User,
        randomizer: RandomEntityGenerator,
        session: Session,
        user_service: UserService,
        fake_redis: aioredis.Redis,
        redis_online: RedisOnlineUserService,
        default_user_auth_headers: dict[str, str]):
    default_user.date_of_birth = datetime.date.today().replace(year=2000)
    default_user.rating = 100
    default_user.gender = Gender.ATTACK_HELICOPTER
    default_user.set_location({
        'country': 'Russia', 'city': 'Moscow', 'flag': 'F'
    })
    # --------------------------------------------------------------------------
    user_1 = randomizer.generate_random_user()
    user_1.rating = 90
    user_1.gender = Gender.ATTACK_HELICOPTER
    user_1.set_location({
        'country': 'Russia', 'city': 'Moscow', 'flag': 'F'
    })
    user_1.date_of_birth = datetime.date.today().replace(year=2000)

    user_2 = randomizer.generate_random_user()
    user_2.rating = 80
    user_2.gender = Gender.FEMALE
    user_2.set_location({
        'country': 'Russia', 'city': 'Moscow', 'flag': 'F'
    })
    user_2.date_of_birth = datetime.date.today().replace(year=2000)

    user_3 = randomizer.generate_random_user()
    user_3.rating = 70
    user_3.gender = Gender.MALE
    user_3.set_location({
        'country': 'Russia', 'city': 'Moscow', 'flag': 'F'
    })
    user_3.date_of_birth = datetime.date.today().replace(year=2001)

    user_4 = randomizer.generate_random_user()
    user_4.rating = 60
    user_4.gender = Gender.MALE
    user_4.set_location({
        'country': 'USA', 'city': 'New York', 'flag': 'F'
    })
    user_4.date_of_birth = datetime.date.today().replace(year=2005)

    user_5 = randomizer.generate_random_user()
    user_5.rating = 50
    user_5.gender = Gender.FEMALE
    user_5.set_location({
        'country': 'USA', 'city': 'New York', 'flag': 'F'
    })
    user_5.date_of_birth = datetime.date.today().replace(year=2005)
    session.commit()
    # --------------------------------------------------------------------------
    # populating caches
    cache_service = CountryCacheService(session, fake_redis)
    await cache_service.populate_country_cache()
    popular_service = PopularUserService(session, fake_redis)
    await popular_service.populate_popular_cache()

    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch_popular",
        headers=default_user_auth_headers,
        json={
            'country': 'Russia'
        }
    )
    assert response.status_code == 200
    resp_data = response.json()
    assert [user['id'] for user in resp_data] == \
           [str(user_1.id), str(user_2.id),str(user_3.id)]

    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch_popular",
        headers=default_user_auth_headers,
        json={
            'country': 'Russia',
            'gender': 'male'
        }
    )
    assert response.status_code == 200
    resp_data = response.json()
    assert [user['id'] for user in resp_data] == \
           [str(user_3.id)]

    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch_popular",
        headers=default_user_auth_headers,
        json={
            'gender': 'female'
        }
    )
    assert response.status_code == 200
    resp_data = response.json()
    assert [user['id'] for user in resp_data] == \
           [str(user_2.id), str(user_5.id)]

    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch_popular",
        headers=default_user_auth_headers,
        json={
        }
    )
    assert response.status_code == 200
    resp_data = response.json()
    assert [user['id'] for user in resp_data] == \
           [str(user_1.id), str(user_2.id),
            str(user_3.id), str(user_4.id), str(user_5.id)]

    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch_popular",
        headers=default_user_auth_headers,
        json={
            'limit': 3
        }
    )
    assert response.status_code == 200
    resp_data = response.json()
    assert [user['id'] for user in resp_data] == \
           [str(user_1.id), str(user_2.id)]

    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch_popular",
        headers=default_user_auth_headers,
        json={
            'limit': 3,
            'offset': 3
        }
    )
    assert response.status_code == 200
    resp_data = response.json()
    assert [user['id'] for user in resp_data] == \
           [str(user_3.id), str(user_4.id), str(user_5.id)]

    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch_popular",
        headers=default_user_auth_headers,
        json={
            'limit': 500
        }
    )
    assert response.status_code == 200
    resp_data = response.json()
    assert [user['id'] for user in resp_data] == \
           [str(user_1.id), str(user_2.id),
            str(user_3.id), str(user_4.id), str(user_5.id)]

    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch_popular",
        headers=default_user_auth_headers,
        json={
            'offset': 500
        }
    )
    assert response.status_code == 200
    resp_data = response.json()
    assert [user['id'] for user in resp_data] == []
