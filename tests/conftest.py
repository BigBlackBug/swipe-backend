import logging
import os
import secrets
import sys
import time
from typing import Dict, Generator

import docker
import pytest
import sqlalchemy.event
from docker.models.containers import Container
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
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


@pytest.fixture(scope='session')
def db_setup(request):
    stop_container = os.environ.get('SWIPE_TEST_STOP_DB_CONTAINER', False)
    client = docker.from_env()
    containers: list[Container] = client.containers.list(filters={
        'name': 'test_pg'
    })
    if not containers:
        pg_container: Container = client.containers.run(
            'postgres:latest', name='test_pg', detach=True,
            ports={'5432/tcp': 5432}, environment={
                'POSTGRES_PASSWORD': 'postgres'
            })
        logger.info("Waiting for testdb to initialize")
        time.sleep(10)

        res = pg_container.exec_run(
            "psql -U postgres -c 'create database postgres_test'")
        if res.exit_code != 0:
            raise RuntimeError('Unable to create a test database')
    else:
        pg_container = containers[0]

    # and even though I'm creating a dedicated engine here,
    # I still need to supply proper settings because the engine import
    # is executed before fixtures
    engine = create_engine(settings.DATABASE_URL, future=True,
                           echo=settings.ENABLE_SQL_ECHO, pool_pre_ping=True)
    SessionClass = sessionmaker(autocommit=False, autoflush=False,
                                future=True, bind=engine)
    # setting up test database
    logger.info("Recreating database")
    ModelBase.metadata.drop_all(bind=engine)
    ModelBase.metadata.create_all(bind=engine)

    def finalizer():
        if stop_container:
            logger.info("Stopping db container")
            pg_container.remove(force=True)

    request.addfinalizer(finalizer)
    return engine, SessionClass


@pytest.fixture(scope='session')
def test_app():
    return main.init_app()


@pytest.fixture
def session(db_setup) -> Generator:
    logger.info("Starting a database session")
    engine, SessionClass = db_setup

    connection = engine.connect()
    transaction = connection.begin()
    session = SessionClass(bind=connection)

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

    logger.info("Closing the database session")
    # Rollback the parent transaction, restoring the state before the test ran.
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(session, test_app) -> Generator:
    def test_database():
        yield session

    # database.db is a dependency used by the app
    test_app.dependency_overrides[database.db] = test_database
    # base_url is mandatory because starlette devs can be dumb sometimes
    yield TestClient(test_app, base_url='http://localhost')
    del test_app.dependency_overrides[database.db]


@pytest.fixture
def test_user_auth_headers(client: TestClient) -> Dict[str, str]:
    resp = client.post(f"{settings.API_V1_PREFIX}/auth",
                       json=default_test_user.dict())
    assert resp.status_code == 200 or resp.status_code == 201
    token = resp.json()['access_token']
    return {'Authorization': f'Bearer {token}'}
