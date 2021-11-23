import pytest
from sqlalchemy.orm import Session

from swipe.swipe_server.misc.randomizer import RandomEntityGenerator
from swipe.swipe_server.users import models
from swipe.swipe_server.users.enums import Gender
from swipe.swipe_server.users.schemas import PopularFilterBody, UserUpdate, \
    LocationSchema
from swipe.swipe_server.users.services import RedisUserService, UserService, \
    CacheService


@pytest.mark.anyio
async def test_redis_fetch_online_country(
        default_user: models.User,
        redis_service: RedisUserService,
        user_service: UserService,
        randomizer: RandomEntityGenerator,
        session: Session):
    user_service.update_user(default_user, UserUpdate(
        location=LocationSchema(country='Russia', city='Moscow',
                                flag='a')))
    default_user.gender = Gender.FEMALE

    user_r_s_m = randomizer.generate_random_user()
    user_service.update_user(user_r_s_m, UserUpdate(
        location=LocationSchema(country='Russia', city='Saint Petersburg',
                                flag='a')))
    user_r_s_m.gender = Gender.MALE
    session.add(user_r_s_m)

    user_r_s_m2 = randomizer.generate_random_user()
    user_service.update_user(user_r_s_m2, UserUpdate(
        location=LocationSchema(country='Russia', city='Saint Petersburg',
                                flag='a')))
    user_r_s_m2.gender = Gender.MALE
    user_r_s_m2.rating = 500
    session.add(user_r_s_m2)

    user_r_s_f = randomizer.generate_random_user()
    user_service.update_user(user_r_s_f, UserUpdate(
        location=LocationSchema(country='Russia', city='Saint Petersburg',
                                flag='a')))
    user_r_s_f.gender = Gender.FEMALE
    session.add(user_r_s_f)

    user_u_n_f = randomizer.generate_random_user()
    user_service.update_user(user_u_n_f, UserUpdate(
        location=LocationSchema(country='USA', city='New York',
                                flag='a')))
    user_u_n_f.gender = Gender.FEMALE
    session.add(user_u_n_f)

    user_u_n_h = randomizer.generate_random_user()
    user_service.update_user(user_u_n_h, UserUpdate(
        location=LocationSchema(country='USA', city='New York',
                                flag='a')))
    user_u_n_h.gender = Gender.ATTACK_HELICOPTER
    session.add(user_u_n_h)
    session.commit()

    cache_service = CacheService(user_service, redis_service)
    await cache_service.populate_country_cache()
    await cache_service.populate_popular_cache()

    result: list[str] = await redis_service.get_popular_users(
        PopularFilterBody(gender=Gender.MALE, country='Russia'))
    assert set(result) == {
        str(user_r_s_m.id), str(user_r_s_m2.id)}

    result: list[str] = await redis_service.get_popular_users(
        PopularFilterBody(gender=Gender.FEMALE, city='New York'))
    assert set(result) == {
        str(user_u_n_f.id)}

    result: list[str] = await redis_service.get_popular_users(
        PopularFilterBody(country='USA'))
    assert set(result) == {
        str(user_u_n_f.id), str(user_u_n_h.id)}
