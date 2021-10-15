from __future__ import annotations

import enum
from datetime import datetime
from typing import Tuple, Union


class UserInterests(str, enum.Enum):
    WORK = 'work'
    FRIENDSHIP = 'friendship'
    FLIRTING = 'flirting'
    NETWORKING = 'networking'
    CHAT = 'chat'
    LOVE = 'love'


class Gender(str, enum.Enum):
    MALE = 'male'
    FEMALE = 'female'
    ATTACK_HELICOPTER = 'attack_helicopter'


class AuthProvider(str, enum.Enum):
    GOOGLE = 'google'
    VK = 'vk'
    SNAPCHAT = 'snapchat'
    APPLE_ID = 'apple_id'


class RecurrenceRate(str, enum.Enum):
    NEVER = 'never'
    SOMETIMES = 'sometimes'
    REGULARLY = 'regularly'


class ZodiacSign(str, enum.Enum):
    ARIES = ('овен', ((20, 3), (19, 4)))
    TAURUS = ('телец', ((20, 4), (20, 5)))
    GEMINI = ('близнецы', ((21, 5), (20, 6)))
    CANCER = ('рак', ((21, 6), (22, 7)))
    LEO = ('лев', ((23, 7), (22, 8)))
    VIRGO = ('дева', ((23, 8), (22, 9)))
    LIBRA = ('весы', ((23, 9), (22, 10)))
    SCORPIO = ('скорпион', ((23, 10), (21, 11)))
    SAGITTARIUS = ('стрелец', ((22, 11), (21, 12)))
    CAPRICORN = ('козерог', ((22, 12), (19, 1)))
    AQUARIUS = ('водолей', ((20, 1), (17, 2)))
    PISCES = ('рыбы', ((18, 2), (19, 3)))

    def __new__(cls, description: str, dates: Tuple):
        obj = str.__new__(cls, [description])
        obj._value_ = description
        obj.dates = dates
        return obj

    @classmethod
    def from_date(cls, birth_date: Union[str, datetime.date]) -> ZodiacSign:
        if isinstance(birth_date, str):
            birth_date = datetime.strptime(birth_date, '%Y-%M-%d').date()

        item: ZodiacSign
        for item in cls:
            if (birth_date.month == item.dates[0][1]
                and birth_date.day >= item.dates[0][0]) \
                    or (birth_date.month == item.dates[1][1]
                        and birth_date.day <= item.dates[1][0]):
                return item
