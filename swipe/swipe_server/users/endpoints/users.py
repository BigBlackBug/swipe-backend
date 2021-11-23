import datetime
import logging
from uuid import UUID

from dateutil.relativedelta import relativedelta
from fastapi import Depends, Body, APIRouter, HTTPException
from sqlalchemy.orm import Session
from starlette import status
from starlette.responses import Response

import swipe.swipe_server.misc.dependencies
from swipe.swipe_server.misc import security
from swipe.swipe_server.users.models import User
from swipe.swipe_server.users.schemas import UserCardPreviewOut, \
    OnlineFilterBody, UserOut, PopularFilterBody
from swipe.swipe_server.users.services import UserService, RedisUserService, \
    UserRequestCacheSettings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    '/fetch_popular',
    name='Fetch users according to the filter',
    responses={
        200: {'description': 'List of users according to filter'},
        400: {'description': 'Bad Request'},
    },
    response_model=list[UserCardPreviewOut])
async def fetch_list_of_users(
        filter_params: PopularFilterBody = Body(...),
        user_service: UserService = Depends(),
        redis_service: RedisUserService = Depends(),
        current_user: User = Depends(security.get_current_user)):
    # TODO maybe store whole users?
    popular_users: list[str] = \
        await redis_service.get_popular_users(filter_params)

    collected_users = user_service.get_users(
        current_user.id, user_ids=popular_users)
    collected_users = sorted(collected_users,
                             key=lambda user: user.rating, reverse=True)
    return [
        UserCardPreviewOut.patched_from_orm(user)
        for user in collected_users
    ]


@router.post(
    '/fetch',
    name='Fetch online users according to the filter',
    responses={
        200: {'description': 'List of users according to filter'},
        400: {'description': 'Bad Request'},
    },
    response_model=list[UserCardPreviewOut])
async def fetch_list_of_users(
        filter_params: OnlineFilterBody = Body(...),
        user_service: UserService = Depends(),
        redis_service: RedisUserService = Depends(),
        current_user: User = Depends(security.get_current_user)):
    """
    All fields are optional. Check default values.
    Important point - ignore_users is supposed to be used
    when fetching users for the popular list
    """
    age_delta = relativedelta(datetime.date.today(), current_user.date_of_birth)
    age = round(age_delta.years + age_delta.months / 12)

    collected_user_ids: set[str] = set()
    ignored_user_ids = set(filter_params.ignore_users)
    age_difference = 0

    logger.info(f"Got filter params {filter_params}")
    # FEED filtered by same country by default)
    # premium filtered by gender
    # premium filtered by location(whole country/my city)
    while len(collected_user_ids) <= filter_params.limit:
        current_cache_settings = UserRequestCacheSettings(
            age=age,
            age_diff=age_difference,
            current_country=current_user.location.country,
            gender_filter=filter_params.gender,
            city_filter=filter_params.city
        )
        current_user_ids: set[str] = \
            await redis_service.find_user_ids(current_cache_settings)
        if not current_user_ids:
            logger.info(
                f"Cache not found for {current_cache_settings.cache_key()}, "
                f"saving")
            current_user_ids = set(user_service.find_user_ids(
                current_user, gender=filter_params.gender,
                age_difference=age_difference,
                city=filter_params.city))
            await redis_service.store_user_ids(
                current_cache_settings, current_user_ids)

        for user in current_user_ids:
            user = str(user)
            if user not in ignored_user_ids:
                ignored_user_ids.add(user)
                collected_user_ids.add(user)

        if age_difference >= filter_params.max_age_difference:
            break

        # increasing search boundaries
        age_difference += 2

    collected_user_ids = await redis_service.filter_blacklist(
        current_user.id, collected_user_ids)
    collected_user_ids = await redis_service.filter_online_users(
        collected_user_ids)

    collected_users = user_service.get_users(current_user.id,
                                             user_ids=collected_user_ids)

    collected_users = sorted(
        collected_users,
        key=lambda user: \
            abs(current_user.date_of_birth - user.date_of_birth).days
    )
    return [
        UserCardPreviewOut.patched_from_orm(user)
        for user in collected_users[:filter_params.limit]
    ]


@router.post(
    '/{user_id}/block',
    name='Block a user',
    responses={
        204: {
            'description': 'User has been blocked',
        },
        404: {
            'description': 'User not found'
        },
        409: {
            'description': 'User is already blocked by you'
        }
    })
async def block_user(
        user_id: UUID,
        user_service: UserService = Depends(),
        redis_service: RedisUserService = Depends(),
        db: Session = Depends(swipe.swipe_server.misc.dependencies.db),
        current_user: User = Depends(security.get_current_user)):
    target_user = user_service.get_user(user_id)
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Not found')

    user_service.update_blacklist(
        str(current_user.id), str(target_user.id))

    await redis_service.add_to_blacklist(
        str(current_user.id), str(target_user.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    '/{user_id}',
    name='Get a single user',
    response_model=UserOut)
async def fetch_user(
        user_id: UUID,
        user_service: UserService = Depends(),
        current_user: User = Depends(security.get_current_user)):
    user = user_service.get_user(user_id)
    user_out: UserOut = UserOut.patched_from_orm(user)
    return user_out
