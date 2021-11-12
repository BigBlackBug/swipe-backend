from __future__ import annotations

import io
from tempfile import SpooledTemporaryFile
from typing import IO

from PIL import Image

AVATAR_WIDTH = 30


def compress_image(image_source: bytes | SpooledTemporaryFile):
    if isinstance(image_source, bytes):
        image: Image = Image.open(io.BytesIO(image_source))
    else:
        image: Image = Image.open(image_source)
    # TODO off by one pixel, meh
    width, height = image.size[0], image.size[1]
    if width > height:
        cropped = image.crop(
            (width / 2 - height / 2, 0, width, width / 2 + height / 2))
    else:
        cropped = image.crop(
            (0, height / 2 - width / 2, width, height / 2 + width / 2))
    cropped.thumbnail((AVATAR_WIDTH, AVATAR_WIDTH))
    output_bytes = io.BytesIO()
    cropped.save(output_bytes, format='PNG')
    return output_bytes.getvalue()
