import datetime
import logging
from uuid import UUID

from dateutil.relativedelta import relativedelta
from fastapi import Depends, Body, APIRouter, HTTPException
from sqlalchemy.orm import Session
from starlette import status
from starlette.responses import Response

import swipe.swipe_server.misc.dependencies
from swipe.settings import settings
from swipe.swipe_server.misc import security
from swipe.swipe_server.users.models import User
from swipe.swipe_server.users.schemas import UserCardPreviewOut, \
    OnlineFilterBody, UserOut, PopularFilterBody
from swipe.swipe_server.users.services import UserService, RedisUserService, \
    OnlineUserRequestCacheParams, UserRequestCacheSettings

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
    logger.info(f"Fetching popular users with {filter_params}")
    # TODO maybe store whole users?
    popular_users: list[str] = \
        await redis_service.get_popular_users(filter_params)

    logger.info(f"Got popular users for {filter_params}: {popular_users}")
    collected_users = user_service.get_users(
        current_user.id, user_ids=popular_users)
    collected_users = sorted(collected_users,
                             key=lambda user: user.rating, reverse=True)

    return [
        UserCardPreviewOut.patched_from_orm(user)
        for user in collected_users
    ]


@router.post(
    '/fetch_online',
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

    user_cache = UserRequestCacheSettings(
        user_id=str(current_user.id),
        gender_filter=filter_params.gender,
        city_filter=filter_params.city
    )
    # the user's been away from the screen for too long or changed settings
    # let's start from the beginning
    if filter_params.invalidate_cache:
        ignored_user_ids: set[str] = set()
        await redis_service.drop_online_response_cache(str(current_user.id))
        logger.info(f"User {current_user.id} request cache invalidated")
    else:
        # previously fetched users will be ignored
        ignored_user_ids: set[str] = \
            await redis_service.get_cached_online_response(user_cache)
        logger.info(
            f"User request cache, key:{user_cache.cache_key()}, "
            f"{ignored_user_ids}")

    age_difference = settings.ONLINE_USER_DEFAULT_AGE_DIFF

    logger.info(f"Got filter params {filter_params}")
    # FEED filtered by same country by default)
    # premium filtered by gender
    # premium filtered by location(whole country/my city)
    while len(collected_user_ids) <= filter_params.limit:
        # saving caches for typical requests
        # I'm 25, give me users from Russia within 2 years of my age
        # this cache refers only to users in db as online-ness is checked later
        current_cache_settings = OnlineUserRequestCacheParams(
            age=age,
            age_diff=age_difference,
            current_country=current_user.location.country,
            gender_filter=filter_params.gender,
            city_filter=filter_params.city
        )
        current_user_ids: set[str] = \
            await redis_service.find_user_ids(current_cache_settings)
        if current_user_ids is None:
            logger.info(
                f"Cache not found for {current_cache_settings.cache_key()}, "
                f"querying database")
            current_user_ids = set(user_service.find_user_ids(
                current_user, gender=filter_params.gender,
                age_difference=age_difference,
                city=filter_params.city))
            logger.info(f"Got {collected_user_ids} "
                        f"for settings {current_cache_settings.cache_key()}. "
                        f"Saving cache")
            await redis_service.store_user_ids(
                current_cache_settings, current_user_ids)

        for user in current_user_ids:
            if user not in ignored_user_ids:
                ignored_user_ids.add(user)
                collected_user_ids.add(user)

        if age_difference >= settings.ONLINE_USER_MAX_AGE_DIFF:
            break

        # increasing search boundaries
        age_difference += settings.ONLINE_USER_AGE_DIFF_STEP

    collected_user_ids = await redis_service.filter_blacklist(
        current_user.id, collected_user_ids)
    collected_user_ids = await redis_service.filter_online_users(
        collected_user_ids)

    logger.info(f"Saving user request cache for {user_cache.cache_key()}: "
                f"{collected_user_ids}")

    if not collected_user_ids:
        return []

    # adding currently returned users to cache
    await redis_service.save_cached_online_response(
        user_cache, collected_user_ids)

    collected_users = user_service.get_users(current_user.id,
                                             user_ids=collected_user_ids)

    collected_users = sorted(
        collected_users,
        key=lambda user:
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
