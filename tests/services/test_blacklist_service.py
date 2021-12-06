import aioredis
import pytest
from sqlalchemy.orm import Session

from swipe.swipe_server.misc.randomizer import RandomEntityGenerator
from swipe.swipe_server.users import models
from swipe.swipe_server.users.services.redis_services import RedisBlacklistService
from swipe.swipe_server.users.services.services import UserService, BlacklistService


@pytest.mark.anyio
async def test_add_to_blacklist(
        session: Session,
        fake_redis: aioredis.Redis,
        randomizer: RandomEntityGenerator,
        blacklist_service: BlacklistService,
        redis_blacklist: RedisBlacklistService,
        user_service: UserService,
        default_user: models.User,
        default_user_auth_headers: dict[str, str]):
    # --------------------------------------------------------------------------
    user_1 = randomizer.generate_random_user()
    user_2 = randomizer.generate_random_user()
    user_3 = randomizer.generate_random_user()
    user_4 = randomizer.generate_random_user()
    session.commit()

    blacklist_service = BlacklistService(session, fake_redis)
    default_user_id = str(default_user.id)
    await blacklist_service.update_blacklist(default_user_id, str(user_1.id))
    await blacklist_service.update_blacklist(default_user_id, str(user_2.id))
    await blacklist_service.update_blacklist(default_user_id, str(user_3.id))
    # the reverse should add to blacklist too
    await blacklist_service.update_blacklist(
        str(user_4.id), default_user_id)
    # --------------------------------------------------------
    expected_blacklist = {str(user_1.id), str(user_2.id), str(user_3.id),
                          str(user_4.id)}
    cached_blacklist = await redis_blacklist.get_blacklist(default_user_id)
    db_blacklist = await user_service.fetch_blacklist(default_user_id)

    assert cached_blacklist == expected_blacklist
    assert db_blacklist == expected_blacklist
