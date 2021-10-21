import random

from PIL import Image, ImageDraw, ImageFont

from settings import constants

AVATAR_WIDTH = 640
AVATAR_HEIGHT = 1024
CIRCLE_SIZE = 40


def generate_random_avatar(username: str) -> Image:
    img = Image.new(mode="RGB", size=(AVATAR_WIDTH, AVATAR_HEIGHT),
                    color=(145, 219, random.randint(150, 250)))
    font = ImageFont.truetype(str(
        constants.BASE_DIR.joinpath('content', 'Herculanum.ttf').absolute()),
        size=70)
    stroke_width = 2
    text = "{}\n{}".format(*username.split())

    draw = ImageDraw.Draw(img)
    text_width, text_height = \
        draw.multiline_textsize(text, font, stroke_width=stroke_width)

    for _ in range(15):
        x = random.randint(0, AVATAR_WIDTH - CIRCLE_SIZE)
        y = random.randint(0, AVATAR_HEIGHT - CIRCLE_SIZE)
        draw.ellipse((x, y, min(x + CIRCLE_SIZE, AVATAR_WIDTH),
                      min(y + CIRCLE_SIZE, AVATAR_HEIGHT)),
                     fill=(random.randint(5, 100), random.randint(100, 170),
                           random.randint(0, 255)))

    draw.multiline_text((
        AVATAR_WIDTH / 2 - text_width / 2,
        AVATAR_HEIGHT / 2 - text_height / 2),
        text=text, stroke_width=stroke_width, fill="#f00", font=font)
    return img
