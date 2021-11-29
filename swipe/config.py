import logging.config


def configure_logging():
    # TODO add current user to context
    logging.config.dictConfig(LOGGING_CONFIG)


class PackagePathFilter(logging.Filter):
    def filter(self, record):
        pathname = record.pathname
        if '/swipe/' in pathname:
            index = pathname.index('/swipe/')
            record.pathname = 'app->' + pathname[index + len('/swipe/'):]
        elif '/site-packages/' in pathname:
            index = pathname.index('/site-packages/')
            record.pathname = \
                'lib->' + pathname[index + len('/site-packages/'):]
        return record


LOGGING_CONFIG: dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "[%(asctime)s] [%(levelname)s] [%(processName)s] | "
                      "%(pathname)s@%(lineno)d | %(message)s"
        },
        "access": {
            "()": "uvicorn.logging.AccessFormatter",
            "fmt": '[%(asctime)s] [%(levelname)s] [%(processName)s] %(name)s | '
                   '%(client_addr)s - "%(request_line)s" %(status_code)s',
        },
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "filters": ['special', ]
        },
        "access": {
            "formatter": "access",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
        "null": {
            "class": "logging.NullHandler"
        },
    },
    'filters': {
        'special': {
            '()': 'swipe.config.PackagePathFilter'
        }
    },
    "loggers": {
        "uvicorn": {
            "handlers": ["default", ],
            "propagate": False,
            "filters": ['special', ]
        },
        'alembic': {
            'handlers': ['default', ],
            'propagate': False,
            "filters": ['special', ]
        },
        # using stock logger for sqlalchemy
        "sqlalchemy.engine": {
            "handlers": ["null", ],
            "propagate": False,
        },
        "websockets": {
            "handlers": ["default", ],
            "propagate": False,
            "filters": ['special', ]
        },
        # "uvicorn.error": {"handlers": ["default"], "level": "INFO"},
        "uvicorn.access": {
            "handlers": ["access", ],
            "propagate": False
        },

        "root": {
            "handlers": ["default", ],
            "level": "INFO",
        },
    },
}
