import datetime
import logging
import time
import uuid
from typing import Optional
from uuid import UUID

import requests
from dateutil.relativedelta import relativedelta
from fastapi import Depends
from jose import jwt
from jose.constants import ALGORITHMS
from sqlalchemy import select, cast, String, update, delete, func, desc
from sqlalchemy.orm import Session, Load, joinedload, Bundle

from swipe.settings import settings, constants
from swipe.swipe_server import utils
from swipe.swipe_server.misc import dependencies
from swipe.swipe_server.misc.errors import SwipeError
from swipe.swipe_server.misc.storage import storage_client
from swipe.swipe_server.users import schemas
from swipe.swipe_server.users.enums import Gender, AccountStatus
from swipe.swipe_server.users.models import User, AuthInfo, Location, IDList, \
    blacklist_table
from swipe.swipe_server.users.schemas import CallFeedback, RatingUpdateReason
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
        user = self.db.execute(
            select(User).where(User.id == user_id)
        ).scalar_one_or_none()
        if user and user.deactivation_date:
            raise SwipeError(f"User {user_id} is deactivated")
        return user

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
            self, user_ids: Optional[IDList] = None) -> list[User]:
        clause = True if user_ids is None else User.id.in_(user_ids)
        return self.db.query(User).where(clause).options(
            Load(User).load_only('id', 'name', 'photos', 'date_of_birth',
                                 'last_online'),
            joinedload(User.location)
        ).all()

    def get_global_chat_preview(
            self, user_ids: Optional[IDList] = None) -> list[User]:
        clause = True if user_ids is None else User.id.in_(user_ids)
        return self.db.query(User).where(clause).options(
            Load(User).load_only('id', 'name', 'avatar_id')
        ).all()

    def get_user_date_of_birth(self, user_id: UUID) -> Optional[User]:
        query = self.db.query(User).where(User.id == user_id).options(
            Load(User).load_only("date_of_birth"),
        )
        return query.one_or_none()

    def get_avatar_url(self, user_id: UUID) -> Optional[str]:
        query = self.db.query(User.avatar_id).where(User.id == user_id)
        row = query.one_or_none()
        if row:
            return storage_client.get_image_url(row.avatar_id)
        return None

    def update_user(
            self,
            user_object: User,
            user_update: schemas.UserUpdate) -> User:
        logger.debug(f'Got update body ex defaults: '
                     f'{user_update.dict(exclude_defaults=True)}')
        trimmed_data = user_update.dict(
            exclude_defaults=True, exclude_none=True, exclude_unset=True)

        logger.debug(f'Trimmed update data: {trimmed_data}')
        for k, v in trimmed_data.items():
            logger.debug(f'Updating field {k} with value {v}')
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

        logger.info(f"Updating avatar of {user.id}")
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
        logger.info(f"Deleting photo {photo_id}")
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
        logger.debug(f"Checking auth_info on user from {user_payload}")
        auth_info = self.db.execute(
            select(AuthInfo, User.id). \
                join(User). \
                where(AuthInfo.auth_provider
                      == user_payload.auth_provider). \
                where(AuthInfo.provider_user_id
                      == user_payload.provider_user_id)). \
            scalar_one_or_none()

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
        logger.info(f"Adding {swipe_number} swipes to {user_id}")

        new_swipes = self.db.execute(
            update(User).where(User.id == user_id).
                values(swipes=(User.swipes + swipe_number)).
                returning(User.swipes)).scalar_one()
        self.db.commit()
        return new_swipes

    def delete_user(self, user: User):
        logger.info(f"Deleting user {user.id}")
        user.delete_photos()
        self.db.execute(delete(User).where(User.id == user.id))
        self.db.commit()

    def deactivate_user(self, user: User):
        logger.info(f"Deactivating user {user.id}")
        self.db.execute(
            update(User).where(User.id == user.id)
                .values(deactivation_date=datetime.datetime.now(),
                        account_status=AccountStatus.DEACTIVATED))
        self.db.execute(delete(AuthInfo).where(AuthInfo.user_id == user.id))
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
            where(User.deactivation_date == None). \
            where(User.account_status == AccountStatus.ACTIVE). \
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
        logger.info(f"Fetching blacklist of {user_id}")
        blocked_by_me = select(
            cast(blacklist_table.columns.blocked_user_id, String)) \
            .where(blacklist_table.columns.blocked_by_id == user_id)

        blocked_me = select(
            cast(blacklist_table.columns.blocked_by_id, String)) \
            .where(blacklist_table.columns.blocked_user_id == user_id)
        return set(self.db.execute(
            blocked_me.union(blocked_by_me)
        ).scalars())

    def add_call_feedback(
            self, target_user: User, feedback: CallFeedback) -> int:
        rating_diff = constants.RATING_CALL_FEEDBACK_DIFF
        logger.info(f"Adding {rating_diff} rating to {target_user.id} "
                    f"due to {feedback}")

        if feedback == CallFeedback.THUMBS_DOWN:
            new_rating = max(0, target_user.rating - rating_diff)
        else:
            new_rating = target_user.rating + rating_diff

        target_user.rating = new_rating
        self.db.commit()
        return new_rating

    def use_swipes(self, target_user: User, number_of_swipes: int = 1) -> int:
        if target_user.swipes < 1:
            raise SwipeError(f"{target_user.id} has 0 swipes left")

        logger.info(f"Reducing swipe number of {target_user.id} "
                    f"by {number_of_swipes}")
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

        logger.info(f"Adding {rating_diff} rating to {user_id}")
        new_rating = self.db.execute(
            update(User).where(User.id == user_id).
                values(rating=(User.rating + rating_diff)).
                returning(User.rating)).scalar_one()
        self.db.commit()

        logger.info(f"{user_id} {new_rating = }")
        return new_rating

    def check_token(self, user_id: str, token: str):
        logger.debug(f"Checking for {user_id} token in DB")
        return self.db.execute(
            select(AuthInfo).join(User). \
                where(AuthInfo.user_id == user_id). \
                where(AuthInfo.access_token == token). \
                where(User.deactivation_date == None)). \
            scalar_one_or_none()

    def get_matchmaking_preview(self, user_id: str) -> User:
        logger.debug(f"Fetching chat matchmaking preview of {user_id}")
        return self.db.query(User). \
            where(User.id == user_id). \
            options(Load(User).load_only('gender', 'date_of_birth')). \
            one_or_none()

    def get_deactivated_users(self, since: datetime.datetime) -> list[UUID]:
        logger.debug(f'Fetching deactivated users since {since}')
        return self.db.execute(
            select(User.id).where(User.deactivation_date >= since)
        ).scalars().all()
