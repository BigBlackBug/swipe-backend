import logging
import os
import time
from typing import Generator

import docker
import pytest
import sqlalchemy.event
from PIL import Image
from aioredis import Redis
from docker.models.containers import Container
from fakeredis._aioredis2 import FakeRedis
from httpx import AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

import swipe.swipe_server.misc.dependencies
from swipe import config
from swipe.settings import settings
from swipe.swipe_server import swipe_app
from swipe.swipe_server.chats.services import ChatService
from swipe.swipe_server.misc.database import ModelBase
from swipe.swipe_server.misc.randomizer import RandomEntityGenerator
from swipe.swipe_server.users import models
from swipe.swipe_server.users.schemas import AuthenticationIn
from swipe.swipe_server.users.services.blacklist_service import BlacklistService
from swipe.swipe_server.users.services.online_cache import \
    RedisOnlineUserService
from swipe.swipe_server.users.services.redis_services import \
    RedisLocationService, RedisBlacklistService, RedisPopularService, \
    RedisSwipeReaperService, RedisUserFetchService, RedisChatCacheService, \
    RedisUserCacheService
from swipe.swipe_server.users.services.user_service import UserService

config.configure_logging()
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
            'postgres:14', name='test_pg', detach=True,
            auto_remove=True,
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
    return swipe_app.init_app()


@pytest.fixture
async def fake_redis():
    redis = FakeRedis(decode_responses=True)
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
async def client(session, fake_redis, test_app) -> Generator:
    def test_database():
        yield session

    def patched_redis():
        yield fake_redis

    # database.db is a dependency used by the app
    test_app.dependency_overrides[
        swipe.swipe_server.misc.dependencies.db] = test_database
    test_app.dependency_overrides[
        swipe.swipe_server.misc.dependencies.redis] = patched_redis
    # base_url is mandatory because starlette devs can be dumb sometimes
    client = AsyncClient(app=test_app, base_url='http://localhost')
    yield client
    del test_app.dependency_overrides[swipe.swipe_server.misc.dependencies.db]
    del test_app.dependency_overrides[
        swipe.swipe_server.misc.dependencies.redis]
    await client.aclose()


@pytest.fixture
def default_user(randomizer: RandomEntityGenerator,
                 session: Session) -> models.User:
    new_user = randomizer.generate_random_user()
    new_user.name = 'default_user'
    new_user.photos = ['default_photo.png']
    new_user.avatar_id = 'whatever_avatar.png'
    session.commit()
    return new_user


@pytest.fixture
def randomizer(user_service: UserService,
               chat_service: ChatService) -> RandomEntityGenerator:
    return RandomEntityGenerator(user_service, chat_service)


@pytest.fixture
def user_service(session: Session) -> UserService:
    return UserService(session)


@pytest.fixture
def redis_user(fake_redis: Redis) -> RedisUserCacheService:
    return RedisUserCacheService(fake_redis)


@pytest.fixture
def redis_online(fake_redis: Redis) -> RedisOnlineUserService:
    return RedisOnlineUserService(fake_redis)


@pytest.fixture
def redis_fetch(fake_redis: Redis) -> RedisUserFetchService:
    return RedisUserFetchService(fake_redis)


@pytest.fixture
def redis_popular(fake_redis: Redis) -> RedisPopularService:
    return RedisPopularService(fake_redis)


@pytest.fixture
def redis_location(fake_redis: Redis) -> RedisLocationService:
    return RedisLocationService(fake_redis)


@pytest.fixture
def redis_blacklist(fake_redis: Redis) -> RedisBlacklistService:
    return RedisBlacklistService(fake_redis)


@pytest.fixture
def redis_chats(fake_redis: Redis) -> RedisChatCacheService:
    return RedisChatCacheService(fake_redis)


@pytest.fixture
def redis_swipes(fake_redis: Redis) -> RedisSwipeReaperService:
    return RedisSwipeReaperService(fake_redis)


@pytest.fixture
def blacklist_service(session: Session, fake_redis: Redis) -> BlacklistService:
    return BlacklistService(session, fake_redis)


@pytest.fixture
def chat_service(session: Session) -> ChatService:
    return ChatService(session)


@pytest.fixture
def random_image(randomizer: RandomEntityGenerator) -> Image:
    return randomizer.generate_random_avatar('what woot')


@pytest.fixture
def default_user_auth_headers(
        user_service: UserService, default_user: models.User) -> dict[str, str]:
    token = user_service.create_access_token(
        default_user, AuthenticationIn(
            auth_provider=default_user.auth_info.auth_provider,
            provider_user_id=default_user.auth_info.provider_user_id,
        ))
    return {'Authorization': f'Bearer {token}'}
