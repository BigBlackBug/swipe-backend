import datetime

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.orm import Session

from swipe.settings import settings
from swipe.swipe_server.misc.randomizer import RandomEntityGenerator
from swipe.swipe_server.users.enums import Gender
from swipe.swipe_server.users.models import User
from swipe.swipe_server.users.services import RedisUserService, UserService, \
    UserRequestCacheSettings


@pytest.mark.anyio
async def test_user_fetch_basic(
        client: AsyncClient,
        default_user: User,
        randomizer: RandomEntityGenerator,
        session: Session,
        redis_service: RedisUserService,
        default_user_auth_headers: dict[str, str]):
    default_user.date_of_birth = datetime.date.today().replace(year=2000)

    # --------------------------------------------------------------------------
    user_1 = randomizer.generate_random_user()
    user_1.date_of_birth = datetime.date.today().replace(year=2000)
    user_1.location.country = 'Russia'
    await redis_service.connect_user(user_1.id)

    user_2 = randomizer.generate_random_user()
    user_2.date_of_birth = datetime.date.today().replace(year=2000)
    user_2.location.country = 'Russia'
    await redis_service.connect_user(user_2.id)

    user_3 = randomizer.generate_random_user()
    user_3.date_of_birth = datetime.date.today().replace(year=2001)
    user_3.location.country = 'Russia'
    await redis_service.connect_user(user_3.id)

    user_4 = randomizer.generate_random_user()
    user_4.date_of_birth = datetime.date.today().replace(year=2005)
    user_4.location.country = 'Russia'
    await redis_service.connect_user(user_4.id)
    session.commit()
    # --------------------------------------------------------------------------

    # ignore+offline+all genders+whole country
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch_online",
        headers=default_user_auth_headers,
        json={
            'limit': 10
        }
    )

    assert response.status_code == 200
    resp_data = response.json()
    assert {user['id'] for user in resp_data} == \
           {str(user_1.id), str(user_2.id), str(user_3.id), str(user_4.id)}


@pytest.mark.anyio
async def test_user_fetch_offline_limit(
        client: AsyncClient,
        default_user: User,
        randomizer: RandomEntityGenerator,
        session: Session,
        redis_service: RedisUserService,
        default_user_auth_headers: dict[str, str]):
    default_user.date_of_birth = datetime.date.today().replace(year=2000)

    # --------------------------------------------------------------------------
    user_1 = randomizer.generate_random_user()
    user_1.date_of_birth = datetime.date.today().replace(year=2000)
    user_1.location.country = 'Russia'
    await redis_service.connect_user(user_1.id)

    user_2 = randomizer.generate_random_user()
    user_2.date_of_birth = datetime.date.today().replace(year=2001)
    user_2.location.country = 'Russia'
    await redis_service.connect_user(user_2.id)

    user_3 = randomizer.generate_random_user()
    user_3.date_of_birth = datetime.date.today().replace(year=2002)
    user_3.location.country = 'Russia'
    await redis_service.connect_user(user_3.id)

    user_4 = randomizer.generate_random_user()
    user_4.date_of_birth = datetime.date.today().replace(year=2003)
    user_4.location.country = 'Russia'
    session.commit()
    # --------------------------------------------------------------------------

    # ignore+offline+all genders+whole country+small limit
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch_online",
        headers=default_user_auth_headers,
        json={
            'limit': 2,
        }
    )

    assert response.status_code == 200
    resp_data = response.json()
    assert len(resp_data) == 2
    assert resp_data[0]['id'] == str(user_1.id)
    assert resp_data[1]['id'] == str(user_2.id)


@pytest.mark.anyio
async def test_user_fetch_online_gender(
        client: AsyncClient,
        default_user: User,
        randomizer: RandomEntityGenerator,
        redis_service: RedisUserService,
        session: Session,
        default_user_auth_headers: dict[str, str]):
    default_user.date_of_birth = datetime.date.today().replace(year=2000)

    # --------------------------------------------------------------------------
    user_1 = randomizer.generate_random_user()
    user_1.name = 'user1'
    user_1.date_of_birth = datetime.date.today().replace(year=2000)
    user_1.gender = Gender.FEMALE
    user_1.location.country = 'Russia'

    user_2 = randomizer.generate_random_user()
    user_2.name = 'user2'
    user_2.date_of_birth = datetime.date.today().replace(year=2000)
    user_2.gender = Gender.FEMALE
    user_2.location.country = 'Russia'

    user_3 = randomizer.generate_random_user()
    user_3.name = 'user3'
    user_3.date_of_birth = datetime.date.today().replace(year=2001)
    user_3.gender = Gender.MALE
    await redis_service.connect_user(user_3.id)
    user_3.location.country = 'Russia'

    user_4 = randomizer.generate_random_user()
    user_4.name = 'user4'
    user_4.date_of_birth = datetime.date.today().replace(year=2005)
    user_4.gender = Gender.MALE
    user_4.location.country = 'Russia'

    user_5 = randomizer.generate_random_user()
    user_5.name = 'user5'
    user_5.date_of_birth = datetime.date.today().replace(year=2002)
    user_5.gender = Gender.ATTACK_HELICOPTER
    user_5.location.country = 'Russia'
    session.commit()
    # --------------------------------------------------------------------------

    # online+gender
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch_online",
        headers=default_user_auth_headers,
        json={
            'gender': 'male'
        }
    )

    assert response.status_code == 200
    resp_data = response.json()
    assert {user['id'] for user in resp_data} == {str(user_3.id)}


@pytest.mark.anyio
async def test_user_fetch_online_city_check_cache(
        client: AsyncClient,
        default_user: User,
        randomizer: RandomEntityGenerator,
        redis_service: RedisUserService,
        session: Session,
        default_user_auth_headers: dict[str, str]):
    default_user.date_of_birth = datetime.date.today().replace(year=2000)

    # --------------------------------------------------------------------------
    user_1 = randomizer.generate_random_user()
    user_1.name = 'user1'
    user_1.date_of_birth = datetime.date.today().replace(year=2000)
    user_1.gender = Gender.FEMALE
    user_1.set_location({
        'country': 'Russia', 'city': 'Moscow', 'flag': 'F'
    })
    session.add(user_1)

    user_2 = randomizer.generate_random_user()
    user_2.name = 'user2'
    user_2.date_of_birth = datetime.date.today().replace(year=2000)
    user_2.gender = Gender.FEMALE
    user_2.set_location({
        'country': 'Russia', 'city': 'Moscow', 'flag': 'F'
    })
    session.add(user_2)

    user_3 = randomizer.generate_random_user()
    user_3.name = 'user3'
    user_3.date_of_birth = datetime.date.today().replace(year=2001)
    user_3.gender = Gender.MALE
    await redis_service.connect_user(user_3.id)
    user_3.set_location({
        'country': 'Russia', 'city': 'Saint Petersburg', 'flag': 'F'
    })
    session.add(user_3)

    user_4 = randomizer.generate_random_user()
    user_4.name = 'user4'
    user_4.date_of_birth = datetime.date.today().replace(year=2005)
    await redis_service.connect_user(user_4.id)
    user_4.gender = Gender.MALE
    user_4.set_location({
        'country': 'Russia', 'city': 'Saint Petersburg', 'flag': 'F'
    })
    session.add(user_4)

    user_44 = randomizer.generate_random_user()
    user_44.name = 'user44'
    user_44.date_of_birth = datetime.date.today().replace(year=2005)
    await redis_service.connect_user(user_44.id)
    user_44.gender = Gender.ATTACK_HELICOPTER
    user_44.set_location({
        'country': 'Russia', 'city': 'Saint Petersburg', 'flag': 'F'
    })
    session.add(user_44)

    user_5 = randomizer.generate_random_user()
    user_5.name = 'user5'
    user_5.date_of_birth = datetime.date.today().replace(year=2003)
    user_5.gender = Gender.MALE
    user_5.set_location({
        'country': 'Russia', 'city': 'Saint Petersburg', 'flag': 'F'
    })
    session.add(user_5)
    session.commit()
    # --------------------------------------------------------------------------

    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch_online",
        headers=default_user_auth_headers,
        json={
            'city': 'Saint Petersburg'
        }
    )
    assert response.status_code == 200
    resp_data = response.json()
    assert {user['id'] for user in resp_data} == {str(user_3.id),
                                                  str(user_4.id), str(user_44.id)}

    cached_response = await redis_service.get_cached_online_response(
        UserRequestCacheSettings(user_id=str(default_user.id),
                                 city_filter='Saint Petersburg'))
    assert cached_response == {str(user_3.id), str(user_4.id), str(user_44.id)}

    # -------------------refetching with a new user----------------------

    await redis_service.connect_user(user_5.id)
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch_online",
        headers=default_user_auth_headers,
        json={
            'city': 'Saint Petersburg'
        }
    )
    assert response.status_code == 200
    resp_data = response.json()
    assert {user['id'] for user in resp_data} == {str(user_5.id)}

    # cache now contains all four
    cached_response = await redis_service.get_cached_online_response(
        UserRequestCacheSettings(user_id=str(default_user.id),
                                 city_filter='Saint Petersburg'))
    assert cached_response == \
           {str(user_3.id), str(user_4.id), str(user_44.id), str(user_5.id)}

    # -------------------invalidating cache with new settings----------------
    # user 2 went online
    await redis_service.connect_user(user_2.id)
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch_online",
        headers=default_user_auth_headers,
        json={
            'city': 'Moscow',
            'invalidate_cache': True
        }
    )
    assert response.status_code == 200
    resp_data = response.json()
    assert {user['id'] for user in resp_data} == {str(user_2.id)}

    # old cache is dead
    old_cached_response = await redis_service.get_cached_online_response(
        UserRequestCacheSettings(user_id=str(default_user.id),
                                 city_filter='Saint Petersburg'))
    assert old_cached_response == set()
    # new cache contains only moscow
    cached_response = await redis_service.get_cached_online_response(
        UserRequestCacheSettings(user_id=str(default_user.id),
                                 city_filter='Moscow'))
    assert cached_response == {str(user_2.id)}


@pytest.mark.anyio
async def test_user_fetch_blacklist(
        client: AsyncClient,
        default_user: User,
        randomizer: RandomEntityGenerator,
        session: Session,
        user_service: UserService,
        redis_service: RedisUserService,
        default_user_auth_headers: dict[str, str]):
    default_user.date_of_birth = datetime.date.today().replace(year=2000)

    # --------------------------------------------------------------------------
    user_1 = randomizer.generate_random_user()
    user_1.name = 'user1'
    user_1.date_of_birth = datetime.date.today().replace(year=2000)
    user_1.gender = Gender.FEMALE
    user_1.set_location({
        'country': 'Russia', 'city': 'Moscow', 'flag': 'F'
    })

    user_2 = randomizer.generate_random_user()
    user_2.name = 'user2'
    user_2.date_of_birth = datetime.date.today().replace(year=2000)
    user_2.gender = Gender.FEMALE
    user_2.set_location({
        'country': 'Russia', 'city': 'Moscow', 'flag': 'F'
    })

    user_3 = randomizer.generate_random_user()
    user_3.name = 'user3'
    user_3.date_of_birth = datetime.date.today().replace(year=2001)
    user_3.gender = Gender.MALE
    user_3.set_location({
        'country': 'Russia', 'city': 'Saint Petersburg', 'flag': 'F'
    })

    user_4 = randomizer.generate_random_user()
    user_4.name = 'user4'
    user_4.date_of_birth = datetime.date.today().replace(year=2005)
    user_4.gender = Gender.MALE
    user_4.set_location({
        'country': 'Russia', 'city': 'Saint Petersburg', 'flag': 'F'
    })

    user_5 = randomizer.generate_random_user()
    user_5.name = 'user5'
    user_5.date_of_birth = datetime.date.today().replace(year=2002)
    user_5.gender = Gender.ATTACK_HELICOPTER
    user_5.set_location({
        'country': 'Russia', 'city': 'Saint Petersburg', 'flag': 'F'
    })

    user_service.update_blacklist(str(default_user.id), str(user_1.id))
    user_service.update_blacklist(str(default_user.id), str(user_2.id))
    user_service.update_blacklist(str(default_user.id), str(user_3.id))

    await redis_service.add_to_blacklist(str(default_user.id), str(user_1.id))
    await redis_service.add_to_blacklist(str(default_user.id), str(user_2.id))
    await redis_service.add_to_blacklist(str(default_user.id), str(user_3.id))

    await redis_service.connect_user(user_1.id)
    await redis_service.connect_user(user_3.id)
    await redis_service.connect_user(user_4.id)
    await redis_service.connect_user(user_5.id)
    session.commit()
    # --------------------------------------------------------------------------

    # offline
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch_online",
        headers=default_user_auth_headers, json={}
    )

    assert response.status_code == 200
    resp_data = response.json()
    assert {user['id'] for user in resp_data} == {str(user_4.id),
                                                  str(user_5.id)}
