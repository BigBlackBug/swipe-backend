import logging.config

from asgi_correlation_id import correlation_id_filter

from swipe.settings import settings


def configure_logging():
    logging.config.dictConfig(LOGGING_CONFIG)


class PackagePathFilter(logging.Filter):
    def _patch_pathname(self, record, piece: str):
        pathname = record.pathname
        if piece in pathname:
            index = pathname.index(piece)
            record.pathname = 'app->' + pathname[index + len(piece):]
        return record

    def filter(self, record):
        record = self._patch_pathname(record, '/swipe/')
        record = self._patch_pathname(record, '/bin/')
        record = self._patch_pathname(record, '/site-packages/')
        return record


LOGGING_CONFIG: dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "[%(asctime)s] [%(levelname)-5s] "
                      "[%(correlation_id)-6s] | "
                      "%(pathname)s@%(lineno)d | %(message)s"
        },
        "access": {
            "()": "uvicorn.logging.AccessFormatter",
            "fmt": '[%(asctime)s] [%(levelname)-5s] '
                   '[%(correlation_id)-6s] | '
                   '%(name)s | %(client_addr)s - '
                   '"%(request_line)s" %(status_code)s',
        },
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "filters": ['special', 'correlation_id']
        },
        "access": {
            "formatter": "access",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "filters":  ['special', 'correlation_id']
        },
        "null": {
            "class": "logging.NullHandler"
        },
    },
    'filters': {
        'special': {
            '()': PackagePathFilter
        },
        'correlation_id': {
            '()': correlation_id_filter(uuid_length=6)
        },
    },
    "loggers": {
        "botocore": {
            "handlers": ["default", ],
            "level": "INFO",
            "propagate": False,
        },
        "uvicorn": {
            "handlers": ["null", ],
            "propagate": False,
        },
        "asyncio": {
            "handlers": ["null", ],
            "propagate": False,
        },
        'alembic': {
            'handlers': ['default', ],
            'propagate': False,
        },
        # using stock logger for sqlalchemy
        "sqlalchemy.engine": {
            "handlers": ["null", ],
            "propagate": False,
        },
        "websockets": {
            "handlers": ["default", ],
            "propagate": False,
        },
        # "uvicorn.error": {"handlers": ["default"], "level": "INFO"},
        "uvicorn.access": {
            "handlers": ["access", ],
            "propagate": False,
        },
        "root": {
            "handlers": ["default", ],
            "level": settings.SWIPE_LOGGING_LEVEL,
        },
    },
}
