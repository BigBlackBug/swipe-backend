import datetime
import functools
import logging
from uuid import UUID

from aioredis import Redis
from fastapi import Depends, Body, APIRouter, HTTPException
from starlette import status
from starlette.responses import Response, RedirectResponse

from swipe.swipe_server import events
from swipe.swipe_server.misc import security, dependencies
from swipe.swipe_server.misc.storage import storage_client
from swipe.swipe_server.users.models import User
from swipe.swipe_server.users.schemas import UserCardPreviewOut, \
    OnlineFilterBody, UserOut, PopularFilterBody, CallFeedback
from swipe.swipe_server.users.services.blacklist_service import BlacklistService
from swipe.swipe_server.users.services.fetch_service import FetchUserService
from swipe.swipe_server.users.services.online_cache import \
    RedisOnlineUserService
from swipe.swipe_server.users.services.redis_services import \
    RedisPopularService, RedisBlacklistService, RedisChatCacheService, \
    RedisUserCacheService
from swipe.swipe_server.users.services.user_service import UserService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    '/deactivated',
    name='Get a list of deactivated users',
    response_model=list[UUID])
async def fetch_deactivated_users(
        since: datetime.datetime,
        user_service: UserService = Depends(),
        current_user_id: UUID = Depends(security.auth_user_id)):
    user_ids = user_service.get_deactivated_users(since)
    return user_ids


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
    logger.info(f"Fetching popular users for {current_user_id} "
                f"with {filter_params}")
    popular_users: list[str] = \
        await redis_popular.get_popular_user_ids(filter_params)
    try:
        # we don't need to see ourselves in the list
        popular_users.remove(str(current_user_id))
    except ValueError:
        pass

    # TODO I might benefit from a heap insertion
    logger.info(f"Got {len(popular_users)} popular users from cache")
    users_data: list[str] = \
        await redis_popular.get_user_card_previews(popular_users)
    collected_users = [
        UserCardPreviewOut.parse_raw(user_data)
        for user_data in users_data if user_data is not None
    ]

    logger.info(f"Got {len(collected_users)} popular users card previews")
    # TODO don't need to sort that? check why the fuck popular users
    # are not inserted to the cache in the correct order in the first place
    collected_users = sorted(collected_users,
                             key=lambda user: user.rating, reverse=True)

    return collected_users


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
        redis_chats: RedisChatCacheService = Depends(),
        redis_blacklist: RedisBlacklistService = Depends(),
        user_service: UserService = Depends(),
        redis: Redis = Depends(dependencies.redis),
        current_user_id: UUID = Depends(security.auth_user_id)):
    """
    If the size of the returned list is smaller than limit, it means
    there are no more users and further requests make no sense
    """
    fetch_service = FetchUserService(RedisOnlineUserService(redis), redis)
    current_user: User = user_service.get_user_date_of_birth(current_user_id)
    blacklist: set[str] = \
        await redis_blacklist.get_blacklist(str(current_user_id))
    logger.info(f"Blacklist of {current_user_id}: {blacklist}")

    chat_partners: set[str] = \
        await redis_chats.get_chat_partners(current_user_id)
    logger.info(f"Chat partners of {current_user_id}: {chat_partners}")

    disallowed_users = chat_partners.union(blacklist)
    collected_user_ids = \
        await fetch_service.collect(
            str(current_user_id), user_age=current_user.age,
            filter_params=filter_params, disallowed_users=disallowed_users)

    if not collected_user_ids:
        return []

    # TODO I might benefit from a heap insertion
    users_data = await redis_online.get_user_card_previews(collected_user_ids)
    collected_users = [
        UserCardPreviewOut.parse_raw(user_data)
        for user_data in users_data if user_data is not None
    ]
    collected_users.sort(
        key=functools.partial(UserCardPreviewOut.sort_key,
                              current_user_dob=current_user.date_of_birth),
        reverse=True
    )

    return collected_users


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

    new_rating = user_service.add_call_feedback(target_user, feedback)

    events.send_rating_changed_event(
        target_user_id=str(user_id), rating=new_rating,
        sender_id=str(current_user_id))
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
    '/photos/{photo_id}',
    name='Get a photo by id')
async def photo_redirect(photo_id: str):
    url = storage_client.get_image_url(photo_id)
    return RedirectResponse(url)


@router.get(
    '/{user_id}',
    name='Get a single user',
    response_model=UserOut)
async def fetch_user(
        user_id: UUID,
        user_service: UserService = Depends(),
        redis_user: RedisUserCacheService = Depends(),
        current_user_id: UUID = Depends(security.auth_user_id)):
    user_out: UserOut = await redis_user.get_user(str(user_id))
    if not user_out:
        logger.debug(f"User {user_id} is not in user cache")
        user = user_service.get_user(user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail=f'User {user_id} not found')

        user_out = UserOut.from_orm(user)
        await redis_user.cache_user(user_out)

    return user_out
