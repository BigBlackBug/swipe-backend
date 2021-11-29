import logging
import re
from uuid import UUID

from fastapi import Depends, Body, HTTPException, UploadFile, File, APIRouter
from starlette import status
from starlette.responses import Response

from swipe.swipe_server.chats.services import ChatService
from swipe.swipe_server.misc import security
from swipe.swipe_server.users import schemas
from swipe.swipe_server.users.models import User, Location
from swipe.swipe_server.users.redis_services import RedisLocationService, \
    RedisOnlineUserService, RedisBlacklistService, RedisPopularService
from swipe.swipe_server.users.schemas import RatingUpdateReason
from swipe.swipe_server.users.services import UserService

IMAGE_CONTENT_TYPE_REGEXP = 'image/(png|jpe?g)'

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    '',
    name="Get current users profile",
    response_model=schemas.UserOut)
async def fetch_user(current_user: User = Depends(security.get_current_user)):
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
        current_user: User = Depends(security.get_current_user)):
    new_rating: int = user_service.add_rating(current_user, reason)

    return {
        'rating': new_rating
    }


@router.patch(
    '',
    name="Update the authenticated users fields",
    response_model=schemas.UserOut,
    response_model_exclude={'photo_urls', })
async def patch_user(
        user_body: schemas.UserUpdate = Body(...),
        user_service: UserService = Depends(),
        redis_location: RedisLocationService = Depends(),
        redis_online: RedisOnlineUserService = Depends(),
        current_user: User = Depends(security.get_current_user)):
    previous_location: Location = current_user.location
    current_user: User = user_service.update_user(current_user, user_body)

    if user_body.location:
        await redis_location.add_cities(
            user_body.location.country, [user_body.location.city])

        logger.info("Removing user from old online request caches")
        await redis_online.update_user_location(
            current_user, previous_location)

    return current_user


@router.delete(
    '',
    name="Delete user", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
        user_service: UserService = Depends(),
        chat_service: ChatService = Depends(),
        redis_blacklist: RedisBlacklistService = Depends(),
        redis_online: RedisOnlineUserService = Depends(),
        redis_popular: RedisPopularService = Depends(),
        current_user: User = Depends(security.get_current_user)):
    # TODO send event to all chat members
    # to remove them from global message list and chats
    chat_ids: list[UUID] = chat_service.fetch_chat_ids(current_user.id)
    for chat_id in chat_ids:
        chat_service.delete_chat(chat_id)

    await redis_online.remove_from_online_caches(current_user)
    await redis_popular.remove_from_popular_cache(current_user)
    await redis_blacklist.drop_blacklist_cache(str(current_user.id))

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
        current_user: User = Depends(security.get_current_user)):
    if not current_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if not re.match(IMAGE_CONTENT_TYPE_REGEXP, file.content_type):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Unsupported image type')

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
        current_user: User = Depends(security.get_current_user)):
    try:
        logger.info(f"Deleting photo {photo_id}")
        user_service.delete_photo(current_user, photo_id)
    except ValueError:
        raise HTTPException(status_code=404, detail='Photo not found')

    return Response(status_code=status.HTTP_204_NO_CONTENT)
