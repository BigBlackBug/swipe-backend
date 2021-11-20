from __future__ import annotations

import io

from PIL import Image

from swipe.swipe_server.misc.errors import SwipeError

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
