import logging
import secrets
import sys
from typing import Dict, Generator

import pytest
import sqlalchemy.event
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import main
from settings import settings
from swipe import database
from swipe.database import ModelBase
from swipe.users import schemas
from swipe.users.enums import AuthProvider

default_test_user = schemas.AuthenticationIn(
    auth_provider=AuthProvider.GOOGLE,
    provider_token=secrets.token_urlsafe(16),
    provider_user_id=secrets.token_urlsafe(16))

logging.basicConfig(stream=sys.stderr,
                    format="[%(asctime)s %(levelname)s|%(processName)s] "
                           "%(name)s %(message)s",
                    level=logging.DEBUG)
logger = logging.getLogger(__name__)

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False,
                                   future=True, bind=database.engine)
# setting up test database
logger.info("Recreating database")
ModelBase.metadata.drop_all(bind=database.engine)
ModelBase.metadata.create_all(bind=database.engine)

test_app = main.init_app()


@pytest.fixture()
def session():
    logger.info("Starting session")
    connection = database.engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    # starting a nested transaction
    nested = connection.begin_nested()

    # If the application code calls session.commit, it will end the nested
    # transaction. Need to start a new one when that happens.
    @sqlalchemy.event.listens_for(session, "after_transaction_end")
    def end_savepoint(session, transaction):
        nonlocal nested
        if not nested.is_active:
            nested = connection.begin_nested()

    yield session

    logger.info("closing session")
    # Rollback the overall transaction, restoring the state before the test ran.
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def client(session) -> Generator:
    def override_get_db():
        yield session

    test_app.dependency_overrides[database.db] = override_get_db
    # base_url is mandatory because starlette devs could be dumb sometimes
    yield TestClient(test_app, base_url='http://localhost')
    del test_app.dependency_overrides[database.db]


@pytest.fixture
def test_user_auth_headers(client: TestClient) \
        -> Dict[str, str]:
    resp = client.post(f"{settings.API_V1_PREFIX}/auth",
                       json=default_test_user.dict())
    assert resp.status_code == 200 or resp.status_code == 201
    token = resp.json()['access_token']
    return {'Authorization': f'Bearer {token}'}
