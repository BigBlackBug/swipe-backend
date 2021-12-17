import datetime
import uuid

import aioredis
import pytest
from httpx import AsyncClient, Response
from sqlalchemy.orm import Session

from swipe.settings import settings
from swipe.swipe_server.misc.randomizer import RandomEntityGenerator
from swipe.swipe_server.users.enums import Gender
from swipe.swipe_server.users.models import User
from swipe.swipe_server.users.services.redis_services import \
    RedisBlacklistService, RedisUserFetchService, UserFetchCacheKey
from swipe.swipe_server.users.services.online_cache import \
    OnlineUserCacheParams, RedisOnlineUserService
from swipe.swipe_server.users.services.blacklist_service import BlacklistService
from swipe.swipe_server.users.services.user_service import UserService


@pytest.mark.anyio
async def test_user_fetch_basic_with_recently_online_check_sort(
        client: AsyncClient,
        default_user: User,
        randomizer: RandomEntityGenerator,
        session: Session,
        user_service: UserService,
        fake_redis: aioredis.Redis,
        redis_online: RedisOnlineUserService,
        default_user_auth_headers: dict[str, str]):
    default_user.date_of_birth = datetime.date.today().replace(year=1998)

    # --------------------------------------------------------------------------
    user_1 = randomizer.generate_random_user()
    user_1.location.country = 'Russia'
    user_1.last_online = None
    user_1.date_of_birth = datetime.date.today().replace(year=2002)
    await redis_online.add_to_online_caches(user_1)

    user_2 = randomizer.generate_random_user()
    user_2.location.country = 'Russia'
    user_2.last_online = None
    user_2.date_of_birth = datetime.date.today().replace(year=2004)
    await redis_online.add_to_online_caches(user_2)

    user_3 = randomizer.generate_random_user()
    user_3.location.country = 'Russia'
    user_3.last_online = None
    user_3.date_of_birth = datetime.date.today().replace(year=2001)
    await redis_online.add_to_online_caches(user_3)

    user_4 = randomizer.generate_random_user()
    user_4.location.country = 'Russia'
    user_4.last_online = None
    user_4.date_of_birth = datetime.date.today().replace(year=2005)
    await redis_online.add_to_online_caches(user_4)
    session.commit()
    # --------------------------------------------------------------------------

    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch",
        headers=default_user_auth_headers,
        json={
            'session_id': str(uuid.uuid4()),
            'country': 'Russia',
            'limit': 10
        }
    )
    assert response.status_code == 200
    resp_data = response.json()
    # all online, sorted according to age
    assert [user['id'] for user in resp_data] == \
           [str(user_3.id), str(user_1.id), str(user_2.id), str(user_4.id)]

    # moving users to recently online
    user_4.last_online = datetime.datetime.utcnow()
    await redis_online.add_to_recently_online_cache(user_4)
    user_3.last_online = \
        datetime.datetime.utcnow() - datetime.timedelta(minutes=30)
    await redis_online.add_to_recently_online_cache(user_3)
    # we have a 10 minute step, so let's use 30 to be sure of the order
    session.commit()

    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch",
        headers=default_user_auth_headers,
        json={
            'session_id': str(uuid.uuid4()),
            'country': 'Russia',
            'limit': 10
        }
    )
    assert response.status_code == 200
    resp_data = response.json()
    # they are still in the response
    # however, 1 an 2 come before, because they are online
    assert [user['id'] for user in resp_data] == \
           [str(user_1.id), str(user_2.id), str(user_3.id), str(user_4.id)]

    # removing user_3 and user_4 from the online list
    await redis_online.update_recently_online_cache(recently_online_ttl=-1)
    # user_3 is gone
    cache_params = OnlineUserCacheParams(
        age=user_3.age, country=user_3.location.country,
        city=user_3.location.city, gender=user_3.gender)
    for key in cache_params.online_keys():
        assert not await fake_redis.sismember(key, str(user_3.id))
    assert not await fake_redis.exists(
        f'{redis_online.RECENTLY_ONLINE_KEY}:{user_3.id}')
    # user_4 is gone
    cache_params = OnlineUserCacheParams(
        age=user_4.age, country=user_4.location.country,
        city=user_4.location.city, gender=user_4.gender)
    for key in cache_params.online_keys():
        assert not await fake_redis.sismember(key, str(user_4.id))
    assert not await fake_redis.exists(
        f'{redis_online.RECENTLY_ONLINE_KEY}:{user_4.id}')

    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch",
        headers=default_user_auth_headers,
        json={
            'session_id': str(uuid.uuid4()),
            'country': 'Russia',
            'limit': 10
        }
    )
    assert response.status_code == 200
    resp_data = response.json()
    # user_3 and user_4 are gone from the response
    assert [user['id'] for user in resp_data] == \
           [str(user_1.id), str(user_2.id)]


@pytest.mark.anyio
async def test_user_fetch_small_limit(
        client: AsyncClient,
        default_user: User,
        randomizer: RandomEntityGenerator,
        session: Session,
        user_service: UserService,
        redis_online: RedisOnlineUserService,
        default_user_auth_headers: dict[str, str]):
    default_user.date_of_birth = datetime.date.today().replace(year=1999)
    default_user.location.country = 'Russia'
    # --------------------------------------------------------------------------
    user_1 = randomizer.generate_random_user()
    user_1.location.country = 'Russia'
    user_1.date_of_birth = datetime.date.today().replace(year=2000)
    await redis_online.add_to_online_caches(user_1)

    user_2 = randomizer.generate_random_user()
    user_2.date_of_birth = datetime.date.today().replace(year=2001)
    user_2.location.country = 'Russia'
    await redis_online.add_to_online_caches(user_2)

    user_3 = randomizer.generate_random_user()
    user_3.date_of_birth = datetime.date.today().replace(year=2002)
    user_3.location.country = 'Russia'
    await redis_online.add_to_online_caches(user_3)

    user_4 = randomizer.generate_random_user()
    user_4.date_of_birth = datetime.date.today().replace(year=2003)
    user_4.location.country = 'Russia'
    session.commit()
    # --------------------------------------------------------------------------

    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch",
        headers=default_user_auth_headers,
        json={
            'session_id': str(uuid.uuid4()),
            'country': 'Russia',
            'limit': 2,
        }
    )

    assert response.status_code == 200
    resp_data = response.json()
    assert len(resp_data) == 2
    # sorted correctly
    assert [user['id'] for user in resp_data] == \
           [str(user_1.id), str(user_2.id)]


@pytest.mark.anyio
async def test_user_fetch_gender(
        client: AsyncClient,
        default_user: User,
        randomizer: RandomEntityGenerator,
        redis_online: RedisOnlineUserService,
        user_service: UserService,
        session: Session,
        default_user_auth_headers: dict[str, str]):
    default_user.date_of_birth = datetime.date.today().replace(year=1999)

    # --------------------------------------------------------------------------
    user_1 = randomizer.generate_random_user()
    user_1.name = 'user1'
    user_1.date_of_birth = datetime.date.today().replace(year=2000)
    user_1.gender = Gender.FEMALE
    user_1.location.country = 'Russia'

    user_2 = randomizer.generate_random_user()
    user_2.name = 'user2'
    user_2.date_of_birth = datetime.date.today().replace(year=2001)
    user_2.gender = Gender.FEMALE
    user_2.location.country = 'Russia'

    user_3 = randomizer.generate_random_user()
    user_3.name = 'user3'
    user_3.date_of_birth = datetime.date.today().replace(year=2002)
    user_3.gender = Gender.MALE
    await redis_online.add_to_online_caches(user_3)
    user_3.location.country = 'Russia'

    user_4 = randomizer.generate_random_user()
    user_4.name = 'user4'
    user_4.date_of_birth = datetime.date.today().replace(year=2005)
    user_4.gender = Gender.MALE
    user_4.location.country = 'Russia'

    user_5 = randomizer.generate_random_user()
    user_5.name = 'user5'
    user_5.date_of_birth = datetime.date.today().replace(year=2006)
    user_5.gender = Gender.ATTACK_HELICOPTER
    user_5.location.country = 'Russia'
    session.commit()
    # --------------------------------------------------------------------------

    # online+gender
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch",
        headers=default_user_auth_headers,
        json={
            'session_id': str(uuid.uuid4()),
            'country': 'Russia',
            'gender': 'male'
        }
    )

    assert response.status_code == 200
    resp_data = response.json()
    assert [user['id'] for user in resp_data] == [str(user_3.id)]


@pytest.mark.anyio
async def test_user_fetch_online_city_cached_requests_all_countries(
        client: AsyncClient,
        default_user: User,
        randomizer: RandomEntityGenerator,
        redis_fetch: RedisUserFetchService,
        redis_online: RedisOnlineUserService,
        user_service: UserService,
        session: Session,
        default_user_auth_headers: dict[str, str]):
    default_user.date_of_birth = datetime.date.today().replace(year=1999)

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
    user_2.date_of_birth = datetime.date.today().replace(year=2001)
    user_2.gender = Gender.FEMALE
    user_2.set_location({
        'country': 'Russia', 'city': 'Moscow', 'flag': 'F'
    })
    session.add(user_2)

    user_3 = randomizer.generate_random_user()
    user_3.name = 'user3'
    user_3.date_of_birth = datetime.date.today().replace(year=2002)
    user_3.gender = Gender.MALE
    user_3.set_location({
        'country': 'Russia', 'city': 'Saint Petersburg', 'flag': 'F'
    })
    await redis_online.add_to_online_caches(user_3)
    session.add(user_3)

    user_4 = randomizer.generate_random_user()
    user_4.name = 'user4'
    user_4.date_of_birth = datetime.date.today().replace(year=2005)
    user_4.gender = Gender.MALE
    user_4.set_location({
        'country': 'Russia', 'city': 'Saint Petersburg', 'flag': 'F'
    })
    await redis_online.add_to_online_caches(user_4)
    session.add(user_4)

    user_44 = randomizer.generate_random_user()
    user_44.name = 'user44'
    user_44.date_of_birth = datetime.date.today().replace(year=2006)
    user_44.gender = Gender.ATTACK_HELICOPTER
    user_44.set_location({
        'country': 'Russia', 'city': 'Saint Petersburg', 'flag': 'F'
    })
    await redis_online.add_to_online_caches(user_44)
    session.add(user_44)

    user_5 = randomizer.generate_random_user()
    user_5.name = 'user5'
    user_5.date_of_birth = datetime.date.today().replace(year=2003)
    user_5.gender = Gender.MALE
    user_5.set_location({
        'country': 'Russia', 'city': 'Saint Petersburg', 'flag': 'F'
    })
    session.add(user_5)

    user_6 = randomizer.generate_random_user()
    user_6.name = 'user5'
    user_6.date_of_birth = datetime.date.today().replace(year=2004)
    user_6.gender = Gender.MALE
    user_6.set_location({
        'country': 'USA', 'city': 'New York', 'flag': 'U'
    })
    session.add(user_6)
    await redis_online.add_to_online_caches(user_6)
    session.commit()

    # --------------------------------------------------------------------------
    session_id = str(uuid.uuid4())
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch",
        headers=default_user_auth_headers,
        json={
            'session_id': session_id,
            'country': 'Russia',
            'city': 'Saint Petersburg'
        }
    )
    assert response.status_code == 200
    resp_data = response.json()
    assert {user['id'] for user in resp_data} == {str(user_3.id),
                                                  str(user_4.id),
                                                  str(user_44.id)}

    cached_response = await redis_fetch.get_response_cache(
        UserFetchCacheKey(session_id=session_id,
                          user_id=str(default_user.id)))
    assert cached_response == {str(user_3.id), str(user_4.id), str(user_44.id)}

    # -------------------fetching with a new user----------------------

    await redis_online.add_to_online_caches(user_5)
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch",
        headers=default_user_auth_headers,
        json={
            'session_id': session_id,
            'country': 'Russia',
            'city': 'Saint Petersburg'
        }
    )
    assert response.status_code == 200
    resp_data = response.json()
    # only one dude should be returned
    assert {user['id'] for user in resp_data} == {str(user_5.id)}

    # cache now contains all four
    cached_response = await redis_fetch.get_response_cache(
        UserFetchCacheKey(session_id=session_id,
                          user_id=str(default_user.id)))
    assert cached_response == \
           {str(user_3.id), str(user_4.id), str(user_44.id), str(user_5.id)}

    # -------------------invalidating cache with new settings----------------
    # settings changed, sending invalidate cache
    new_session_id = str(uuid.uuid4())
    await redis_online.add_to_online_caches(user_2)
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch",
        headers=default_user_auth_headers,
        json={
            'session_id': new_session_id,
            'country': 'Russia',
            'city': 'Moscow'
        }
    )
    assert response.status_code == 200
    resp_data = response.json()
    assert {user['id'] for user in resp_data} == {str(user_2.id)}

    # old cache is dead
    old_cached_response = await redis_fetch.get_response_cache(
        UserFetchCacheKey(session_id=session_id,
                          user_id=str(default_user.id)))
    assert old_cached_response == set()

    # new cache contains only peeps from moscow
    cached_response = await redis_fetch.get_response_cache(
        UserFetchCacheKey(session_id=new_session_id,
                          user_id=str(default_user.id)))
    assert cached_response == {str(user_2.id)}

    # -------------------invalidating cache with new settings----------------
    # settings changed, sending invalidate cache
    # FETCHING EVERYONE
    await redis_online.remove_from_online_caches(user_2)
    previous_session_id = new_session_id
    new_session_id = str(uuid.uuid4())
    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch",
        headers=default_user_auth_headers,
        json={
            'session_id': new_session_id
        }
    )
    assert response.status_code == 200
    resp_data = response.json()
    assert {user['id'] for user in resp_data} == {
        str(user_3.id), str(user_4.id), str(user_44.id),
        str(user_5.id), str(user_6.id)
    }

    # old cache is dead
    old_cached_response = await redis_fetch.get_response_cache(
        UserFetchCacheKey(session_id=previous_session_id,
                          user_id=str(default_user.id)))
    assert old_cached_response == set()

    # new cache contains everyone
    cached_response = await redis_fetch.get_response_cache(
        UserFetchCacheKey(session_id=new_session_id,
                          user_id=str(default_user.id)))
    assert cached_response == {
        str(user_3.id), str(user_4.id), str(user_44.id),
        str(user_5.id), str(user_6.id)
    }


@pytest.mark.anyio
async def test_user_fetch_with_blacklist(
        client: AsyncClient,
        default_user: User,
        randomizer: RandomEntityGenerator,
        session: Session,
        user_service: UserService,
        blacklist_service: BlacklistService,
        redis_online: RedisOnlineUserService,
        redis_blacklist: RedisBlacklistService,
        default_user_auth_headers: dict[str, str]):
    default_user.date_of_birth = datetime.date.today().replace(year=1999)

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
    user_2.date_of_birth = datetime.date.today().replace(year=2001)
    user_2.gender = Gender.FEMALE
    user_2.set_location({
        'country': 'Russia', 'city': 'Moscow', 'flag': 'F'
    })

    user_3 = randomizer.generate_random_user()
    user_3.name = 'user3'
    user_3.date_of_birth = datetime.date.today().replace(year=2002)
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
    user_5.date_of_birth = datetime.date.today().replace(year=2003)
    user_5.gender = Gender.ATTACK_HELICOPTER
    user_5.set_location({
        'country': 'Russia', 'city': 'Saint Petersburg', 'flag': 'F'
    })

    await blacklist_service.update_blacklist(str(default_user.id),
                                             str(user_1.id))
    await blacklist_service.update_blacklist(str(default_user.id),
                                             str(user_2.id))
    await blacklist_service.update_blacklist(str(default_user.id),
                                             str(user_3.id))

    await redis_online.add_to_online_caches(user_1)
    await redis_online.add_to_online_caches(user_3)
    await redis_online.add_to_online_caches(user_4)
    await redis_online.add_to_online_caches(user_5)
    session.commit()
    # --------------------------------------------------------------------------

    response: Response = await client.post(
        f"{settings.API_V1_PREFIX}/users/fetch",
        headers=default_user_auth_headers, json={
            'session_id': str(uuid.uuid4()),
            'country': 'Russia'
        }
    )

    assert response.status_code == 200
    resp_data = response.json()
    assert {user['id'] for user in resp_data} == {str(user_4.id),
                                                  str(user_5.id)}


@pytest.mark.anyio
async def test_user_fetch_single(
        client: AsyncClient,
        default_user: User,
        randomizer: RandomEntityGenerator,
        session: Session,
        default_user_auth_headers: dict[str, str]):
    response: Response = await client.get(
        f"{settings.API_V1_PREFIX}/users/{default_user.id}",
        headers=default_user_auth_headers
    )
    assert response.json()['avatar_url'] == \
           f'{settings.SWIPE_REST_SERVER_HOST}/v1/users/' \
           f'{default_user.id}/avatar'
