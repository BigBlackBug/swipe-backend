import functools
import logging
from uuid import UUID

from fastapi import Depends, Body, APIRouter, HTTPException
from starlette import status
from starlette.responses import Response

from swipe.swipe_server.misc import security
from swipe.swipe_server.users.models import User
from swipe.swipe_server.users.redis_services import RedisPopularService
from swipe.swipe_server.users.schemas import UserCardPreviewOut, \
    OnlineFilterBody, UserOut, PopularFilterBody, CallFeedback
from swipe.swipe_server.users.services import UserService, FetchUserService, \
    BlacklistService

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
        redis_popular: RedisPopularService = Depends(),
        current_user_id: UUID = Depends(security.auth_user_id)):
    """
    If the size of the returned list is smaller than limit, it means
    there are no more users and further requests make no sense
    """
    logger.info(f"Fetching popular users with {filter_params}")
    # TODO maybe store whole users?
    popular_users: list[str] = \
        await redis_popular.get_popular_users(filter_params)

    logger.info(f"Got popular users for {filter_params}: {popular_users}")
    collected_users = \
        user_service.get_user_card_previews(user_ids=popular_users)
    # TODO don't need to sort that?
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
async def fetch_list_of_online_users(
        filter_params: OnlineFilterBody = Body(...),
        fetch_service: FetchUserService = Depends(),
        user_service: UserService = Depends(),
        current_user_id: UUID = Depends(security.auth_user_id)):
    """
    If the size of the returned list is smaller than limit, it means
    there are no more users and further requests make no sense
    """
    current_user: User = user_service.get_user_date_of_birth(current_user_id)
    collected_user_ids = \
        await fetch_service.collect(str(current_user_id),
                                    user_age=current_user.age,
                                    filter_params=filter_params)

    if not collected_user_ids:
        return []

    collected_users: list[UserCardPreviewOut] \
        = await fetch_service.get_user_card_previews(collected_user_ids)

    collected_users.sort(
        key=functools.partial(UserCardPreviewOut.sort_key,
                              current_user_dob=current_user.date_of_birth),
        reverse=True
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
        blacklist_service: BlacklistService = Depends(),
        current_user_id: UUID = Depends(security.auth_user_id)):
    target_user = user_service.get_user(user_id)
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Not found')

    blocked_by_id = str(current_user_id)
    blocked_user_id = str(user_id)

    await blacklist_service.update_blacklist(
        blocked_by_id, blocked_user_id, send_blacklist_event=True)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    '/{user_id}/call_feedback',
    name='Leave feedback for a call with user',
    responses={
        204: {
            'description': 'OK',
        }
    })
async def call_feedback(
        user_id: UUID,
        feedback: CallFeedback = Body(..., embed=True),
        user_service: UserService = Depends(),
        current_user_id: UUID = Depends(security.auth_user_id)):
    target_user = user_service.get_user(user_id)
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Not found')

    user_service.add_call_feedback(target_user, feedback)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    '/{user_id}/swipe_left',
    name='Decline user card',
    responses={
        200: {
            'description': 'OK',
        },
        409: {
            'description': 'User does not have enough swipes'
        }
    })
async def decline_card_offer(
        user_id: UUID,
        user_service: UserService = Depends(),
        blacklist_service: BlacklistService = Depends(),
        current_user_id: UUID = Depends(security.auth_user_id)):
    current_user = user_service.get_user(current_user_id)
    if not current_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Not found')

    new_swipes = user_service.use_swipes(current_user)
    blocked_by_id = str(current_user_id)
    blocked_user_id = str(user_id)

    await blacklist_service.update_blacklist(
        blocked_by_id, blocked_user_id, send_blacklist_event=True)

    return {
        'swipes': new_swipes
    }


@router.get(
    '/{user_id}',
    name='Get a single user',
    response_model=UserOut)
async def fetch_user(
        user_id: UUID,
        user_service: UserService = Depends(),
        current_user_id: UUID = Depends(security.auth_user_id)):
    user = user_service.get_user(user_id)
    user_out: UserOut = UserOut.patched_from_orm(user)
    return user_out
