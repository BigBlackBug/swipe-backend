import logging
import sys


def configure_logging():
    # TODO add operation logging
    # TODO proper logging configuration
    # TODO add current user to context
    logging.basicConfig(stream=sys.stderr,
                        format="[%(asctime)s %(levelname)s|%(processName)s] "
                               "%(name)s %(message)s",
                        level=logging.DEBUG)
    logging.getLogger('botocore')
