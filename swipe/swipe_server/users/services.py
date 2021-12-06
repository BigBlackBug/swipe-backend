import logging
import time
import uuid
from dataclasses import dataclass
from typing import Optional, Iterable
from uuid import UUID

import aioredis
import requests
from aioredis import Redis
from dateutil.relativedelta import relativedelta
from fastapi import Depends
from jose import jwt
from jose.constants import ALGORITHMS
from sqlalchemy import select, delete, func, desc, String, cast, insert, update
from sqlalchemy.engine import Row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, Bundle, Load, joinedload

from swipe.settings import settings, constants
from swipe.swipe_server import utils
from swipe.swipe_server.misc import dependencies
from swipe.swipe_server.misc.errors import SwipeError
from swipe.swipe_server.misc.storage import storage_client
from swipe.swipe_server.users import schemas
from swipe.swipe_server.users.enums import Gender
from swipe.swipe_server.users.models import IDList, User, AuthInfo, Location, \
    blacklist_table
from swipe.swipe_server.users.redis_services import RedisOnlineUserService, \
    RedisBlacklistService, OnlineUserCacheParams, \
    FetchUserCacheKey, RedisPopularService, RedisLocationService, \
    RedisUserFetchService
from swipe.swipe_server.users.schemas import OnlineFilterBody, CallFeedback, \
    RatingUpdateReason, UserCardPreviewOut
from swipe.swipe_server.utils import enable_blacklist

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self,
                 db: Session = Depends(dependencies.db)):
        self.db = db

    def create_user(self,
                    user_payload: schemas.AuthenticationIn) -> User:
        auth_info = AuthInfo(**user_payload.dict())
        user_object = User()
        user_object.auth_info = auth_info

        self.db.add(auth_info)
        self.db.add(user_object)
        self.db.commit()
        self.db.refresh(user_object)
        return user_object

    def find_user_ids(self, current_user: User,
                      gender: Optional[Gender] = None,
                      age_difference: int = 0,
                      city: Optional[str] = None) -> set[str]:
        """
        Return a list of user ids with regards to supplied filters

        :param current_user:
        :param gender: ignore if None
        :param age_difference:
        :param city: ignore if None
        :return:
        """
        city_clause = True if not city else Location.city == city
        gender_clause = True if not gender else User.gender == gender
        min_age = current_user.date_of_birth - relativedelta(
            years=age_difference)
        max_age = current_user.date_of_birth + relativedelta(
            years=age_difference)

        query = select(cast(User.id, String)).join(User.location). \
            where(Location.country == current_user.location.country). \
            where(city_clause). \
            where(gender_clause). \
            where(User.id != current_user.id). \
            where(User.date_of_birth.between(min_age, max_age))

        return self.db.execute(query).scalars().all()

    def get_user(self, user_id: UUID) -> Optional[User]:
        return self.db.execute(
            select(User).where(User.id == user_id)) \
            .scalar_one_or_none()

    def get_user_card_preview(self, user_id: UUID) -> User:
        query = self.db.query(User). \
            where(User.id == user_id).options(
            Load(User).load_only('id', 'name', 'bio', 'zodiac_sign',
                                 'date_of_birth', 'rating', 'interests',
                                 'photos', 'instagram_profile',
                                 'tiktok_profile', 'snapchat_profile',

                                 'gender', 'avatar_id', 'firebase_token',
                                 'last_online'),
            joinedload(User.location)
        )
        return query.one_or_none()

    def get_user_chat_preview(
            self, user_ids: Optional[IDList] = None,
            location: bool = False) -> list[Row]:
        clause = True if user_ids is None else User.id.in_(user_ids)
        if location:
            # TODO load_only
            return self.db.execute(
                select(User.id, User.name, User.photos, User.date_of_birth,
                       User.last_online, Location).
                    join(Location).where(clause)).all()
        else:
            return self.db.execute(
                select(User.id, User.name, User.photos).where(clause)).all()

    def get_global_chat_preview(
            self, user_ids: Optional[IDList] = None) -> list[Row]:
        clause = True if user_ids is None else User.id.in_(user_ids)
        return self.db.execute(
            select(User.id, User.name, User.avatar_id).where(clause)).all()

    def get_user_date_of_birth(self, user_id: UUID):
        query = self.db.query(User).where(User.id == user_id).options(
            Load(User).load_only("date_of_birth"),
        )
        return query.one_or_none()

    def update_user(
            self,
            user_object: User,
            user_update: schemas.UserUpdate) -> User:
        for k, v in user_update.dict(exclude_defaults=True).items():
            if k == 'location':
                user_object.set_location(v)
            else:
                setattr(user_object, k, v)
                if k == 'photos':
                    logger.info(f"Deleting old avatar image "
                                f"{user_object.avatar_id}")
                    storage_client.delete_image(user_object.avatar_id)
                    if len(v) > 0:
                        self._update_avatar(user_object, photo_id=v[0])
                    else:
                        user_object.avatar_id = None
        self.db.commit()
        self.db.refresh(user_object)
        return user_object

    def _update_avatar(self, user: User, photo_id: Optional[str] = None,
                       image_content: Optional[bytes] = None):
        if photo_id:
            img_url = storage_client.get_image_url(photo_id)
            image_content = requests.get(img_url).content
        elif not image_content:
            raise SwipeError(
                "Either photo_id or image_content must be provided")

        avatar_id = f'{uuid.uuid4()}.png'

        compressed_image = utils.compress_image(image_content)
        storage_client.upload_image(avatar_id, compressed_image)
        user.avatar_id = avatar_id

    def add_photo(self, user_object: User, file_content: bytes,
                  extension: str) -> str:
        photo_id = f'{uuid.uuid4()}.{extension}'
        storage_client.upload_image(photo_id, file_content)

        user_object.photos = user_object.photos + [photo_id]
        if len(user_object.photos) == 1:
            self._update_avatar(user_object, image_content=file_content)

        self.db.commit()
        return photo_id

    def delete_photo(self, user_object: User, photo_id: str):
        new_list = list(user_object.photos)
        index = new_list.index(photo_id)
        del new_list[index]

        user_object.photos = new_list
        if index == 0:
            self._update_avatar(user_object, photo_id=new_list[0])

        storage_client.delete_image(photo_id)
        self.db.commit()

    def find_user_by_auth(
            self,
            user_payload: schemas.AuthenticationIn) -> Optional[User]:
        auth_info = self.db.execute(
            select(AuthInfo)
                .where(AuthInfo.auth_provider
                       == user_payload.auth_provider)
                .where(AuthInfo.provider_user_id
                       == user_payload.provider_user_id)) \
            .scalar_one_or_none()
        # TODO check queries for extra joins
        return auth_info.user if auth_info else None

    def create_access_token(self, user_object: User,
                            payload: schemas.AuthenticationIn) -> str:
        payload = schemas.JWTPayload(
            **payload.dict(), user_id=str(user_object.id),
            created_at=time.time_ns()).dict()
        access_token = jwt.encode(
            payload,
            settings.SWIPE_SECRET_KEY, algorithm=ALGORITHMS.HS256)
        user_object.auth_info.access_token = access_token
        self.db.commit()
        return access_token

    def add_swipes(self, user_id: UUID, swipe_number: int) -> int:
        if swipe_number < 0:
            raise ValueError("swipe_number must be positive")
        logger.info(f"Adding {swipe_number} swipes")

        new_swipes = self.db.execute(
            update(User).where(User.id == user_id).
                values(swipes=(User.swipes + swipe_number)).
                returning(User.swipes)).scalar_one()
        self.db.commit()
        return new_swipes

    def get_photo_url(self, image_id: str):
        return storage_client.get_image_url(image_id)

    def delete_user(self, user: User):
        logger.info(f"Deleting user {user.id}")
        user.delete_photos()
        self.db.execute(delete(User).where(User.id == user.id))
        self.db.commit()

    def fetch_locations(self) -> dict[str, list[str]]:
        """
        Returns rows of cities grouped by country.
        Each row has two fields: row.country.country
            and grouped cities: row.cities
        :return: A list of rows.
        """
        query = select(Bundle("country", Location.country),
                       Bundle("cities",
                              func.array_agg(Location.city))).group_by(
            Location.country)
        query_result = self.db.execute(query)
        result = dict()
        for row in query_result.all():
            result[row.country.country] = list(row.cities)[0]
        return result

    def fetch_popular(self, country: Optional[str] = None,
                      gender: Optional[Gender] = None,
                      city: Optional[str] = None,
                      limit: int = 100) -> list[User]:
        if city and not country:
            raise SwipeError("Either none or both country and city must be set")

        city_clause = True if not city else Location.city == city
        country_clause = True if not country else Location.country == country
        gender_clause = True if not gender else User.gender == gender
        query = self.db.query(User). \
            join(User.location). \
            where(country_clause).where(city_clause).where(gender_clause). \
            options(
            Load(User).load_only('id', 'name', 'bio', 'zodiac_sign',
                                 'date_of_birth', 'rating', 'interests',
                                 'photos', 'instagram_profile',
                                 'tiktok_profile', 'snapchat_profile',
                                 'last_online'),
        ).order_by(desc(User.rating)).limit(limit)

        return self.db.execute(query).scalars().all()

    @enable_blacklist(return_value_class=set)
    async def fetch_blacklist(self, user_id: str) -> set[str]:
        blocked_by_me = select(
            cast(blacklist_table.columns.blocked_user_id, String)) \
            .where(blacklist_table.columns.blocked_by_id == user_id)

        blocked_me = select(
            cast(blacklist_table.columns.blocked_by_id, String)) \
            .where(blacklist_table.columns.blocked_user_id == user_id)
        return set(self.db.execute(
            blocked_me.union(blocked_by_me)
        ).scalars())

    def add_call_feedback(self, target_user: User, feedback: CallFeedback):
        rating_diff = constants.CALL_FEEDBACK_RATING_DIFF
        if feedback == CallFeedback.THUMBS_DOWN:
            new_rating = max(0, target_user.rating - rating_diff)
        else:
            new_rating = target_user.rating + rating_diff

        target_user.rating = new_rating
        self.db.commit()

    def use_swipes(self, target_user: User, number_of_swipes: int = 1) -> int:
        if target_user.swipes < 1:
            raise SwipeError(f"{target_user.id} has 0 swipes left")

        target_user.swipes -= number_of_swipes
        self.db.commit()
        return target_user.swipes

    def add_rating(self, user_id: UUID, reason: RatingUpdateReason):
        # TODO move to enum
        if reason == RatingUpdateReason.AD_WATCHED:
            rating_diff = constants.RATING_UPDATE_AD_WATCHED
        elif reason == RatingUpdateReason.FRIEND_REFERRED:
            rating_diff = constants.RATING_UPDATE_FRIEND_REFERRED
        elif reason == RatingUpdateReason.APP_REVIEWED:
            rating_diff = constants.RATING_UPDATE_APP_REVIEWED
        elif reason == RatingUpdateReason.PREMIUM_ACTIVATED:
            rating_diff = constants.RATING_UPDATE_PREMIUM_ACTIVATED
        else:
            rating_diff = 0

        new_rating = self.db.execute(
            update(User).where(User.id == user_id).
                values(rating=(User.rating + rating_diff)).
                returning(User.rating)).scalar_one()
        self.db.commit()

        return new_rating

    def check_token(self, user_id: str, token: str):
        return self.db.execute(
            select(AuthInfo)
                .where(AuthInfo.user_id == user_id) \
                .where(AuthInfo.access_token == token)) \
            .scalar_one_or_none()


@dataclass
class UserPool:
    online_users: list[str]
    head: int = 0


class FetchUserService:
    def __init__(self,
                 redis: Redis = Depends(dependencies.redis)):
        self.redis_fetch = RedisUserFetchService(redis)
        self.redis_popular = RedisPopularService(redis)
        self.redis_online = RedisOnlineUserService(redis)
        self.redis_blacklist = RedisBlacklistService(redis)

    async def collect(self, user_id: str, user_age: int,
                      filter_params: OnlineFilterBody) -> set[str]:
        fetch_cache_params = FetchUserCacheKey(
            session_id=filter_params.session_id,
            user_id=user_id
        )

        await self.redis_fetch.drop_obsolete_caches(fetch_cache_params)
        cached_user_ids: set[str] = \
            await self.redis_fetch.get_response_cache(fetch_cache_params)

        age_difference = settings.ONLINE_USER_DEFAULT_AGE_DIFF

        logger.info(f"Got filter params {filter_params}, "
                    f"previous cache {cached_user_ids}")

        # premium filtered by gender
        # premium filtered by location(whole country/my city)
        blacklist: set[str] = \
            await self.redis_blacklist.get_blacklist(user_id)
        # Russia, SPB, 25+-2,3,4, ALL

        # age->(index,user_list)
        online_users_pool = {}

        result = set()
        while len(result) < filter_params.limit \
                and age_difference <= settings.ONLINE_USER_MAX_AGE_DIFF:
            shift = -1
            # we're going age+0,-1,1,-2,2 etc
            sorted_age_range = [user_age]
            logger.info(f"Current age {user_age}, diff {age_difference}")
            while len(sorted_age_range) < age_difference * 2 + 1:
                sorted_age_range.append(user_age + shift)
                sorted_age_range.append(user_age - shift)
                shift = - (abs(shift) + 1)
            logger.info(f"Checking age range {sorted_age_range}")

            # filling current user pool
            for current_age in sorted_age_range:
                cache_params = OnlineUserCacheParams(
                    age=current_age, country=filter_params.country,
                    city=filter_params.city, gender=filter_params.gender)

                if current_age not in online_users_pool:
                    user_cache = \
                        await self.redis_online.get_online_users(cache_params)
                    user_cache = list(user_cache)
                    online_users_pool[current_age] = UserPool(user_cache)
                    logger.info(f"Got {len(user_cache)} online users "
                                f"for age={current_age}")

            for current_age in sorted_age_range:
                current_pool: UserPool = online_users_pool[current_age]
                # getting one user per age pool
                if current_pool.head < len(current_pool.online_users):
                    candidate = current_pool.online_users[current_pool.head]
                    current_pool.head += 1
                    if candidate not in cached_user_ids \
                            and candidate not in blacklist \
                            and candidate != user_id:
                        logger.info(
                            f"Found {candidate} in user pool "
                            f"for age={current_age}")
                        result.add(candidate)

                if len(result) == filter_params.limit:
                    # got enough users
                    break
            else:
                # online users depleted, extend age_diff and try again
                age_difference += settings.ONLINE_USER_AGE_DIFF_STEP
                logger.info(
                    f"Online users depleted for range {sorted_age_range}, "
                    f"increasing age_difference to {age_difference}")
                continue

        # got enough users or max age diff reached
        logger.info(f"Adding {result} to user request cache "
                    f"for {fetch_cache_params.cache_key()}")
        # adding currently returned users to cache
        await self.redis_fetch.add_to_response_cache(
            fetch_cache_params, result)
        return result

    async def get_online_card_previews(self, user_ids: Iterable[str]) \
            -> list[UserCardPreviewOut]:
        users_data = await self.redis_online.get_user_card_previews(user_ids)
        return [
            UserCardPreviewOut.parse_raw(user_data)
            for user_data in users_data
        ]

    async def get_popular_card_previews(self, user_ids: Iterable[str]) \
            -> list[UserCardPreviewOut]:
        users_data: list[str] = \
            await self.redis_popular.get_user_card_previews(user_ids)
        return [
            UserCardPreviewOut.parse_raw(user_data)
            for user_data in users_data if user_data is not None
        ]


class PopularUserService:
    def __init__(self, db: Session = Depends(dependencies.db),
                 redis: aioredis.Redis = Depends(dependencies.redis)):
        self.user_service = UserService(db)
        self.redis_popular = RedisPopularService(redis)
        self.redis_locations = RedisLocationService(redis)

    async def populate_cache(self, country: Optional[str] = None,
                             city: Optional[str] = None,
                             gender: Optional[Gender] = None):
        users: list[User] = self.user_service.fetch_popular(
            country=country, city=city, gender=gender)
        logger.info(
            f"Got {len(users)} popular users from db for: "
            f"country:{country or 'ALL'}, city:{city or 'ALL'}, "
            f"gender:{gender or 'ALL'}")
        await self.redis_popular.save_popular_users(
            country=country, city=city, gender=gender, users=users)

    async def populate_popular_cache(self):
        logger.info("Populating popular cache")
        locations = self.redis_locations.fetch_locations()

        # global popular cache
        logger.info("Populating global cache")
        await self.populate_cache(gender=Gender.MALE)
        await self.populate_cache(gender=Gender.FEMALE)
        await self.populate_cache()

        async for country, cities in locations:
            logger.info(f"Populating cache for country: '{country}'")
            await self.populate_cache(country=country, gender=Gender.MALE)
            await self.populate_cache(country=country, gender=Gender.FEMALE)
            await self.populate_cache(country=country)

            logger.info(f"Populating cities cache for '{country}', "
                        f"cities: '{cities}'")
            for city in cities:
                await self.populate_cache(
                    country=country, city=city, gender=Gender.MALE)
                await self.populate_cache(
                    country=country, city=city, gender=Gender.FEMALE)
                await self.populate_cache(country=country, city=city)


class CountryCacheService:
    def __init__(self, db: Session, redis: aioredis.Redis):
        self.user_service = UserService(db)
        self.redis_popular = RedisPopularService(redis)
        self.redis_locations = RedisLocationService(redis)

    async def populate_country_cache(self):
        locations: dict[str, list[str]] = self.user_service.fetch_locations()

        logger.info("Dropping country cache")
        await self.redis_locations.drop_country_cache()

        logger.info(
            f"Populating location cache with locations: {locations}")
        for country, cities in locations.items():
            logger.info(f"Saving {cities} to {country}")
            await self.redis_locations.add_cities(country, cities)


class BlacklistService:
    def __init__(self, db: Session = Depends(dependencies.db),
                 redis: aioredis.Redis = Depends(dependencies.redis)):
        self.db = db
        self.redis_blacklist = RedisBlacklistService(redis)

    @enable_blacklist()
    async def update_blacklist(
            self, blocked_by_id: str, blocked_user_id: str,
            send_blacklist_event: bool = False):
        logger.info(f"Adding both {blocked_by_id} and {blocked_user_id}"
                    f"to each others blacklist")
        try:
            self.db.execute(insert(blacklist_table).values(
                blocked_user_id=blocked_user_id,
                blocked_by_id=blocked_by_id))
            self.db.commit()
        except IntegrityError:
            raise SwipeError(f"{blocked_user_id} is "
                             f"already blocked by {blocked_by_id}")

        await self.redis_blacklist.add_to_blacklist_cache(
            blocked_by_id, blocked_user_id)

        if send_blacklist_event:
            # sending 'add to blacklist' event to blocked_user_id
            url = f'{settings.CHAT_SERVER_HOST}/events/blacklist'
            requests.post(url, json={
                'blocked_by_id': blocked_by_id,
                'blocked_user_id': blocked_user_id
            })


class RedisFirebaseService:
    FIREBASE_KEY = 'firebase_tokens'
    FIREBASE_COOLDOWN_KEY = 'firebase_cooldown'

    def __init__(self,
                 redis: aioredis.Redis = Depends(dependencies.redis)):
        self.redis = redis

    async def get_firebase_token(self, user_id: str):
        return await self.redis.hget(self.FIREBASE_KEY, user_id)

    async def remove_token_from_cache(self, user_id: str):
        await self.redis.hdel(self.FIREBASE_KEY, user_id)

    async def add_token_to_cache(self, user_id: str, token: str):
        if not token:
            return
        await self.redis.hset(self.FIREBASE_KEY, user_id, token)

    async def is_on_cooldown(self, sender_id: str, recipient_id: str) -> bool:
        return await self.redis.get(
            f'{self.FIREBASE_COOLDOWN_KEY}:{sender_id}:{recipient_id}')

    async def set_cooldown_token(self,  sender_id: str, recipient_id: str):
        await self.redis.setex(
            f'{self.FIREBASE_COOLDOWN_KEY}:{sender_id}:{recipient_id}',
            time=constants.FIREBASE_NOTIFICATION_COOLDOWN_SEC,
            value='1')
