import logging.config


def configure_logging():
    # TODO add current user to context
    logging.config.dictConfig(LOGGING_CONFIG)


LOGGING_CONFIG: dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "[%(asctime)s %(levelname)s|%(processName)s] | "
                      "%(name)s | %(module)s@%(lineno)d | %(message)s"
        },
        "access": {
            "()": "uvicorn.logging.AccessFormatter",
            "fmt": '[%(asctime)s %(levelname)s|%(processName)s] %(name)s | '
                   '%(client_addr)s - "%(request_line)s" %(status_code)s',
        },
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
        },
        "access": {
            "formatter": "access",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
    },
    "loggers": {
        "uvicorn": {
            "handlers": ["default"],
            "propagate": False
        },
        'alembic': {
            'handlers': ['default'],
            'propagate': False
        },
        # "uvicorn.error": {"handlers": ["default"], "level": "INFO"},
        "uvicorn.access": {
            "handlers": ["access"],
            "propagate": False
        },
        "sqlalchemy": {
            "handlers": ["default"],
            "propagate": False,
        },
        "websockets": {
            "handlers": ["default"],
            "propagate": False,
        },
        "root": {
            "handlers": ["default"], "level": "INFO",
        },
    },
}
