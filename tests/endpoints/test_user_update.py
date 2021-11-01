import datetime

import dateutil.parser
import pytest
from httpx import AsyncClient, Response
from sqlalchemy.orm import Session

from settings import settings
from swipe.users import models
from swipe.users.enums import ZodiacSign
from swipe.users.services import UserService, RedisUserService


@pytest.mark.anyio
async def test_user_update_dob_zodiac(
        client: AsyncClient,
        default_user: models.User,
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
