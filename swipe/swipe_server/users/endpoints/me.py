import logging
import re
from uuid import UUID

import requests
from fastapi import Depends, Body, HTTPException, UploadFile, File, APIRouter
from starlette import status
from starlette.background import BackgroundTasks
from starlette.responses import Response

from swipe.settings import settings
from swipe.swipe_server.chats.models import Chat
from swipe.swipe_server.chats.services import ChatService
from swipe.swipe_server.misc import security
from swipe.swipe_server.users import schemas, swipe_bg_tasks
from swipe.swipe_server.users.models import User, Location
from swipe.swipe_server.users.schemas import RatingUpdateReason
from swipe.swipe_server.users.services.online_cache import \
    RedisOnlineUserService
from swipe.swipe_server.users.services.redis_services import \
    RedisLocationService, \
    RedisBlacklistService
from swipe.swipe_server.users.services.services import UserService, \
    PopularUserService

IMAGE_CONTENT_TYPE_REGEXP = 'image/(png|jpe?g)'

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    '',
    name="Get current users profile",
    response_model=schemas.UserOut)
async def fetch_user(user_service: UserService = Depends(),
                     user_id: UUID = Depends(security.auth_user_id)):
    current_user = user_service.get_user(user_id)
    user_out: schemas.UserOut = schemas.UserOut.patched_from_orm(current_user)
    return user_out


@router.post(
    '/rating', name="Add rating", responses={
        200: {
            "description": "Rating updated",
            "content": {
                "application/json": {
                    "example": {
                        "rating": 100500
                    }
                }
            },
        },
    })
async def add_rating(
        reason: RatingUpdateReason = Body(..., embed=True),
        user_service: UserService = Depends(),
        user_id: UUID = Depends(security.auth_user_id)):
    new_rating: int = user_service.add_rating(user_id, reason)

    return {
        'rating': new_rating
    }


@router.patch(
    '',
    name="Update the authenticated users fields",
    response_model=schemas.UserOut,
    response_model_exclude={'photo_urls', })
async def patch_user(
        background_tasks: BackgroundTasks,
        user_body: schemas.UserUpdate = Body(...),
        user_service: UserService = Depends(),
        redis_location: RedisLocationService = Depends(),
        user_id: UUID = Depends(security.auth_user_id)):
    current_user = user_service.get_user(user_id)
    previous_location: Location = current_user.location
    current_user: User = user_service.update_user(current_user, user_body)

    # they are sending this patch on each login
    if user_body.location:
        # it's a location update
        # so we have to repopulate respective online/popular caches
        if previous_location and not \
                (previous_location.city == user_body.location.city and
                 previous_location.country == user_body.location.country):
            background_tasks.add_task(
                swipe_bg_tasks.update_location_caches, current_user,
                previous_location)
        elif not previous_location:
            await redis_location.add_cities(
                user_body.location.country, [user_body.location.city])
    else:
        # a regular update
        background_tasks.add_task(
            swipe_bg_tasks.update_user_cache, current_user)

    return current_user


@router.delete(
    '',
    name="Delete user", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
        user_service: UserService = Depends(),
        chat_service: ChatService = Depends(),
        redis_blacklist: RedisBlacklistService = Depends(),
        redis_online: RedisOnlineUserService = Depends(),
        popular_service: PopularUserService = Depends(),
        user_id: UUID = Depends(security.auth_user_id)):
    current_user: User = user_service.get_user(user_id)

    # somebody might want to delete user before the location is set
    # e.g. during the registration
    if current_user.location:
        await redis_online.remove_from_online_caches(current_user)

    await redis_blacklist.drop_blacklist_cache(str(current_user.id))

    # repopulating popular caches
    await popular_service.populate_cache(
        country=current_user.location.country,
        city=current_user.location.city,
        gender=current_user.gender)
    await popular_service.populate_cache(
        country=current_user.location.country,
        city=current_user.location.city)

    await popular_service.populate_cache(
        country=current_user.location.country,
        gender=current_user.gender)
    await popular_service.populate_cache(
        country=current_user.location.country)

    await popular_service.populate_cache(
        gender=current_user.gender)
    await popular_service.populate_cache()

    recipients = []
    # fetching only id and user ids
    chats: list[Chat] = chat_service.fetch_chat_members(current_user.id)
    for chat in chats:
        if user_id == chat.initiator_id:
            recipients.append(str(chat.the_other_person_id))
        elif user_id == chat.the_other_person_id:
            recipients.append(str(chat.initiator_id))
        # not relying on cascades because we need to delete images manually
        chat_service.delete_chat(chat.id)

    url = f'{settings.CHAT_SERVER_HOST}/events/user_deleted'
    # if the user has no messages in global chat, send event only
    # to his chat partners
    if chat_service.has_global_chat_messages(current_user.id):
        # they are cascaded but let's do this manually for clarity
        chat_service.delete_global_chat_messages(current_user.id)

        logger.info(f"{current_user.id} has global messages, "
                    f"everyone will be notified")
        requests.post(url, json={
            'user_id': str(user_id),
        })
    elif recipients:
        logger.debug(
            f"{current_user.ud} has no global messages, "
            f"only chat partners {recipients} will be notified")
        # we gotta notify every chat participant that the user is gone
        requests.post(url, json={
            'user_id': str(user_id),
            'recipients': recipients
        })

    user_service.delete_user(current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    '/photos',
    name='Add a photo to the authenticated user',
    responses={
        201: {
            "description": "Uploaded photo data",
            "content": {
                "application/json": {
                    "example": {
                        "photo_id": "", "photo_url": ""
                    }
                }
            },
        },
    },
    status_code=status.HTTP_201_CREATED)
async def add_photo(
        file: UploadFile = File(...),
        user_service: UserService = Depends(UserService),
        user_id: UUID = Depends(security.auth_user_id)):
    if not re.match(IMAGE_CONTENT_TYPE_REGEXP, file.content_type):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Unsupported image type')

    current_user = user_service.get_user(user_id)
    if len(current_user.photos) == User.MAX_ALLOWED_PHOTOS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f'Can not add more than {User.MAX_ALLOWED_PHOTOS} photos')

    _, _, extension = file.content_type.partition('/')

    photo_id = user_service.add_photo(current_user, file.file.read(), extension)
    photo_url = user_service.get_photo_url(photo_id)

    return {'photo_id': photo_id, 'photo_url': photo_url}


@router.delete(
    '/photos/{photo_id}',
    name='Delete an authenticated users photo',
    status_code=status.HTTP_204_NO_CONTENT)
async def delete_photo(
        photo_id: str,
        user_service: UserService = Depends(UserService),
        user_id: UUID = Depends(security.auth_user_id)):
    current_user = user_service.get_user(user_id)
    try:
        logger.info(f"Deleting photo {photo_id}")
        user_service.delete_photo(current_user, photo_id)
    except ValueError:
        raise HTTPException(status_code=404, detail='Photo not found')

    return Response(status_code=status.HTTP_204_NO_CONTENT)
