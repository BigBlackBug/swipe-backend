import functools
import logging
from uuid import UUID

from aioredis import Redis
from fastapi import Depends, Body, APIRouter, HTTPException
from starlette import status
from starlette.responses import Response, RedirectResponse

from swipe.swipe_server.misc import security, dependencies
from swipe.swipe_server.misc.storage import storage_client
from swipe.swipe_server.users.models import User
from swipe.swipe_server.users.schemas import UserCardPreviewOut, \
    OnlineFilterBody, UserOut, PopularFilterBody, CallFeedback
from swipe.swipe_server.users.services.fetch_service import FetchUserService
from swipe.swipe_server.users.services.online_cache import \
    RedisOnlineUserService
from swipe.swipe_server.users.services.redis_services import RedisPopularService
from swipe.swipe_server.users.services.services import UserService, \
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
        redis_popular: RedisPopularService = Depends(),
        current_user_id: UUID = Depends(security.auth_user_id)):
    """
    If the size of the returned list is smaller than limit, it means
    there are no more users and further requests make no sense
    """
    logger.info(f"Fetching popular users with {filter_params}")
    popular_users: list[str] = \
        await redis_popular.get_popular_user_ids(filter_params)
    try:
        # we don't need to see ourselves in the list
        popular_users.remove(str(current_user_id))
    except ValueError:
        pass

    # TODO I might benefit from a heap insertion
    logger.info(f"Got {len(popular_users)} popular users for {filter_params}")
    users_data: list[str] = \
        await redis_popular.get_user_card_previews(popular_users)
    collected_users = [
        UserCardPreviewOut.parse_raw(user_data)
        for user_data in users_data if user_data is not None
    ]

    logger.info(f"Got {len(collected_users)} popular users card "
                f"previews for {filter_params}")
    # TODO don't need to sort that? check why the fuck popular users
    # are not inserted to the cache in the correct order in the first place
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
        redis_online: RedisOnlineUserService = Depends(),
        user_service: UserService = Depends(),
        redis: Redis = Depends(dependencies.redis),
        current_user_id: UUID = Depends(security.auth_user_id)):
    """
    If the size of the returned list is smaller than limit, it means
    there are no more users and further requests make no sense
    """
    fetch_service = FetchUserService(RedisOnlineUserService(redis), redis)
    current_user: User = user_service.get_user_date_of_birth(current_user_id)
    collected_user_ids = \
        await fetch_service.collect(str(current_user_id),
                                    user_age=current_user.age,
                                    filter_params=filter_params)

    if not collected_user_ids:
        return []

    # TODO I might benefit from a heap insertion
    users_data = await redis_online.get_user_card_previews(collected_user_ids)
    collected_users = [
        UserCardPreviewOut.parse_raw(user_data)
        for user_data in users_data
    ]
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
    '/{user_id}/avatar',
    name='Get a single users avatar')
async def avatar_redirect(
        user_id: UUID,
        user_service: UserService = Depends(),
        redis_online: RedisOnlineUserService = Depends()):
    user_data = await redis_online.get_user_card_preview_one(str(user_id))
    if not user_data:
        url = user_service.get_avatar_url(user_id)
        if not url:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    else:
        card_preview = UserCardPreviewOut.parse_raw(user_data)
        url = storage_client.get_image_url(card_preview.avatar_id)

    return RedirectResponse(url)


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
