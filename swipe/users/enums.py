import enum


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
