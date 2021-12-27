from __future__ import annotations

import functools
import io
import logging
from typing import Type

from PIL import Image

from swipe.settings import settings
from swipe.swipe_server.misc.errors import SwipeError

logger = logging.getLogger(__name__)
AVATAR_SIZE = (60, 60)


def compress_image(image_source: bytes) -> bytes:
    if not isinstance(image_source, bytes):
        raise SwipeError("Invalid image content, should be 'bytes'")

    image: Image = Image.open(io.BytesIO(image_source))
    # TODO off by one pixel, meh
    width, height = image.size[0], image.size[1]
    if width > height:
        cropped = image.crop(
            (width / 2 - height / 2, 0, width, width / 2 + height / 2))
    else:
        cropped = image.crop(
            (0, height / 2 - width / 2, width, height / 2 + width / 2))
    cropped.thumbnail(AVATAR_SIZE)
    output_bytes = io.BytesIO()
    cropped.save(output_bytes, format='PNG')
    return output_bytes.getvalue()


def enable_blacklist(
        enable: bool = settings.SWIPE_BLACKLIST_ENABLED,
        return_value_class: Type = None):
    def _decorator(func):
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            if enable:
                return await func(self, *args, **kwargs)
            elif return_value_class:
                logger.info(
                    f"Blacklist disabled, "
                    f"{func.__module__}.{func.__name__} was not executed. "
                    f"Returning {return_value_class()}")
                return return_value_class()
            else:
                return None

        return wrapper

    return _decorator
