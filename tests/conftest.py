import logging
import os
import secrets
import sys
import time
from typing import Generator

import docker
import pytest
import sqlalchemy.event
from aioredis import Redis
from docker.models.containers import Container
from fakeredis._aioredis2 import FakeRedis
from httpx import AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

import main
import swipe.dependencies
from settings import settings
from swipe.database import ModelBase
from swipe.users import schemas, models
from swipe.users.enums import AuthProvider
from swipe.users.services import UserService, RedisService

logging.basicConfig(stream=sys.stderr,
                    format="[%(asctime)s %(levelname)s|%(processName)s] "
                           "%(name)s %(message)s",
                    level=logging.DEBUG)
logger = logging.getLogger(__name__)

default_user_payload = schemas.AuthenticationIn(
    auth_provider=AuthProvider.GOOGLE,
    provider_token=secrets.token_urlsafe(16),
    provider_user_id=secrets.token_urlsafe(16))


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
async def fake_redis():
    redis = FakeRedis()
    yield redis
    await redis.close()


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
def anyio_backend():
    # we don't need trio
    return 'asyncio'


@pytest.fixture
def client(session, fake_redis, test_app) -> Generator:
    def test_database():
        yield session

    def patched_redis():
        yield fake_redis

    # database.db is a dependency used by the app
    test_app.dependency_overrides[swipe.dependencies.db] = test_database
    test_app.dependency_overrides[swipe.dependencies.redis] = patched_redis
    # base_url is mandatory because starlette devs can be dumb sometimes
    yield AsyncClient(app=test_app, base_url='http://localhost')
    del test_app.dependency_overrides[swipe.dependencies.db]
    del test_app.dependency_overrides[swipe.dependencies.redis]


@pytest.fixture
def default_user(user_service: UserService) -> models.User:
    return user_service.create_user(default_user_payload)


@pytest.fixture
def user_service(session: Session) -> UserService:
    return UserService(session)


@pytest.fixture
def redis_service(fake_redis: Redis) -> RedisService:
    return RedisService(fake_redis)


@pytest.fixture
def default_user_auth_headers(
        user_service: UserService, default_user: models.User) -> dict[str, str]:
    token = user_service.create_access_token(default_user, default_user_payload)
    return {'Authorization': f'Bearer {token}'}
