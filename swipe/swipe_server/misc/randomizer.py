import datetime
import io
import random
import secrets
from typing import Optional
from uuid import uuid4

import lorem
import names
from PIL import Image, ImageDraw, ImageFont
from dateutil.relativedelta import relativedelta
from sqlalchemy import select

from swipe.settings import constants
from swipe.swipe_server.chats.models import Chat, ChatStatus, ChatMessage, \
    MessageStatus, \
    GlobalChatMessage, ChatSource
from swipe.swipe_server.chats.services import ChatService
from swipe.swipe_server.misc.errors import SwipeError
from swipe.swipe_server.misc.storage import storage_client
from swipe.swipe_server.users.enums import AuthProvider, ZodiacSign, Gender, \
    UserInterests, \
    RecurrenceRate, NotificationTypes
from swipe.swipe_server.users.models import User
from swipe.swipe_server.users.schemas import AuthenticationIn
from swipe.swipe_server.users.services import UserService

AVATAR_WIDTH = 640
AVATAR_HEIGHT = 1024
CIRCLE_SIZE = 40


class RandomEntityGenerator:
    def __init__(self, user_service: Optional[UserService] = None,
                 chat_service: Optional[ChatService] = None):
        self._user_service = user_service
        self._chat_service = chat_service

    def generate_random_user(self,
                             generate_images: bool = False):
        new_user = self._user_service.create_user(AuthenticationIn(
            auth_provider=AuthProvider.SNAPCHAT,
            provider_user_id=secrets.token_urlsafe(16)))
        new_user.name = names.get_full_name()[:30]
        new_user.bio = lorem.paragraph()[:200]
        new_user.height = random.randint(150, 195)
        new_user.interests = random.sample(list(UserInterests), 3)
        new_user.gender = random.choice(list(Gender))
        new_user.smoking = random.choice(list(RecurrenceRate))
        new_user.drinking = random.choice(list(RecurrenceRate))
        new_user.enabled_notifications = random.choice(list(NotificationTypes))

        birth_date = datetime.date.today().replace(
            year=random.randint(1985, 2003),
            month=random.randint(1, 12),
            day=random.randint(1, 25))
        new_user.date_of_birth = birth_date
        new_user.zodiac_sign = ZodiacSign.from_date(birth_date)
        new_user.rating = random.randint(5, 150)
        new_user.swipes = random.randint(50, 150)
        new_user.set_location({
            'city': random.choice([
                'Moscow', 'Saint Petersburg', 'Magadan', 'Surgut', 'Cherepovets'
            ]),
            'country': 'Russia',
            'flag': '🇷🇺'
        })
        self._user_service.db.commit()
        self._user_service.db.refresh(new_user)

        number_of_images = 4 if generate_images else 0
        for _ in range(number_of_images):
            image = self.generate_random_avatar(new_user.name)
            with io.BytesIO() as output:
                image.save(output, format='png')
                contents = output.getvalue()
                self._user_service.add_photo(new_user, contents, 'png')

        return new_user

    def generate_random_chat(
            self, user_a: User, user_b: User,
            n_messages: int = 10, generate_images: bool = False) -> Chat:
        chat = Chat(status=ChatStatus.ACCEPTED,
                    source=random.choice(list(ChatSource)),
                    initiator=user_a, the_other_person=user_b)
        self._chat_service.db.add(chat)

        people = [user_a, user_b]
        message_time = datetime.datetime.utcnow()
        for _ in range(n_messages):
            message_time -= datetime.timedelta(minutes=random.randint(1, 10))
            sender = random.choice(people)
            if generate_images and random.random() < 0.3:
                # image
                extension = 'png'
                image_id = f'{uuid4()}.{extension}'
                image = self.generate_random_avatar(sender.name)
                with io.BytesIO() as output:
                    image.save(output, format=extension)
                    contents = output.getvalue()
                storage_client.upload_image(image_id, contents)

                message = ChatMessage(
                    timestamp=message_time,
                    status=random.choice(list(MessageStatus)),
                    image_id=image_id,
                    sender=sender)
            else:
                # text
                message = ChatMessage(
                    timestamp=message_time,
                    status=random.choice(list(MessageStatus)),
                    message=lorem.sentence(),
                    sender=sender)

            chat.messages.append(message)

        self._chat_service.db.commit()
        self._chat_service.db.refresh(chat)
        return chat

    def generate_random_global_chat(self, n_messages: int):
        messages = []
        message_time = datetime.datetime.utcnow()
        people = self._chat_service.db.execute(select(User)).scalars().all()
        for _ in range(n_messages):
            message_time -= datetime.timedelta(minutes=random.randint(1, 10))
            sender = random.choice(people)
            message = GlobalChatMessage(
                timestamp=message_time,
                message=lorem.sentence(),
                sender=sender)

            messages.append(message)
            self._chat_service.db.add(message)
        self._chat_service.db.commit()
        for message in messages:
            self._chat_service.db.refresh(message)
        return messages

    def generate_random_avatar(self, username: str) -> Image:
        if not username.strip():
            raise SwipeError("Username should not be empty")

        username_pieces = username.split()
        if len(username_pieces) == 1:
            username_pieces = [username_pieces[0]] * 2
        elif len(username_pieces) > 1:
            username_pieces = username_pieces[:2]
        text = "{}\n{}".format(*username_pieces)

        img = Image.new(mode="RGB", size=(AVATAR_WIDTH, AVATAR_HEIGHT),
                        color=(145, 219, random.randint(150, 250)))
        draw = ImageDraw.Draw(img)

        font = ImageFont.truetype(str(
            constants.BASE_DIR.joinpath(
                'content', 'Herculanum.ttf').absolute()), size=70)
        stroke_width = 2

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
