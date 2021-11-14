import pytest
from sqlalchemy.orm import Session

from swipe.swipe_server.users import models


@pytest.mark.anyio
async def test_fetch_chat_by_members(
        default_user: models.User,
        session: Session):
    assert True
