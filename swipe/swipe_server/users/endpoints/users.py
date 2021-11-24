import datetime
import logging
from uuid import UUID

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
    KeyType, FetchService

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
async def fetch_list_of_popular_users(
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
    # TODO  don't need to sort that?
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
async def fetch_list_of_online_users(
        filter_params: OnlineFilterBody = Body(...),
        fetch_service: FetchService = Depends(),
        user_service: UserService = Depends(),
        current_user: User = Depends(security.get_current_user)):
    """
    All fields are optional. Check default values.
    Important point - ignore_users is supposed to be used
    when fetching users for the popular list
    """

    collected_user_ids = await fetch_service.collect(
        current_user, filter_params, key_type=KeyType.ONLINE_REQUEST)

    if not collected_user_ids:
        return []

    collected_users = user_service.get_users(
        current_user.id, user_ids=collected_user_ids)

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
    '/fetch_cards',
    name='Fetch online user cards according to the filter',
    responses={
        200: {'description': 'List of users according to filter'},
        400: {'description': 'Bad Request'},
    },
    response_model=list[UserCardPreviewOut])
async def fetch_list_of_user_cards(
        filter_params: OnlineFilterBody = Body(...),
        user_service: UserService = Depends(),
        fetch_service: FetchService = Depends(),
        current_user: User = Depends(security.get_current_user)):
    """
    All fields are optional. Check default values.
    Important point - ignore_users is supposed to be used
    when fetching users for the popular list
    """
    collected_user_ids = await fetch_service.collect(
        current_user, filter_params, key_type=KeyType.CARDS_REQUEST)

    if not collected_user_ids:
        return []

    collected_users = user_service.get_users(
        current_user.id, user_ids=collected_user_ids)

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
