from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# https://docs.sqlalchemy.org/en/14/core/pooling.html
# maintains a connection pool
# TCP connections are represented as file descriptors,
# each process must have it's own engine instance,
# pooled connections must not be shared
from settings import settings

engine = create_engine(settings.DATABASE_URL, future=True,
                       echo=settings.ENABLE_SQL_ECHO, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False,
                            future=True, bind=engine)

Base = declarative_base()
