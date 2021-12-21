import logging
import re
from uuid import UUID

from fastapi import Depends, Body, HTTPException, UploadFile, File, APIRouter
from starlette import status
from starlette.background import BackgroundTasks
from starlette.responses import Response

from swipe.swipe_server import events
from swipe.swipe_server.chats.models import Chat
from swipe.swipe_server.chats.services import ChatService
from swipe.swipe_server.misc import security
from swipe.swipe_server.users import schemas, swipe_bg_tasks
from swipe.swipe_server.users.models import User, Location
from swipe.swipe_server.users.schemas import RatingUpdateReason
from swipe.swipe_server.users.services.online_cache import \
    RedisOnlineUserService
from swipe.swipe_server.users.services.popular_cache import PopularUserService
from swipe.swipe_server.users.services.redis_services import \
    RedisLocationService, \
    RedisBlacklistService
from swipe.swipe_server.users.services.user_service import UserService

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

    events.send_rating_changed_event(
        target_user_id=str(user_id), rating=new_rating)
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
            logger.info(f"{user_id} location has changed, "
                        f"updating popular and online caches")
            background_tasks.add_task(
                swipe_bg_tasks.update_location_caches, current_user,
                previous_location)
        elif not previous_location:
            logger.info(f"{user_id} set his location, updating country cache")
            await redis_location.add_cities(
                user_body.location.country, [user_body.location.city])
    else:
        # a regular update
        logger.info(f"Updating online user cache for {user_id}")
        background_tasks.add_task(
            swipe_bg_tasks.update_user_cache, current_user)

    return current_user


@router.delete(
    '',
    name="Delete user", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
        delete: bool = False,
        user_service: UserService = Depends(),
        chat_service: ChatService = Depends(),
        redis_blacklist: RedisBlacklistService = Depends(),
        redis_online: RedisOnlineUserService = Depends(),
        popular_service: PopularUserService = Depends(),
        user_id: UUID = Depends(security.auth_user_id)):
    current_user: User = user_service.get_user(user_id)
    country = current_user.location.country
    city = current_user.location.city
    gender = current_user.gender

    # somebody might want to delete user before the location is set
    # e.g. during the registration
    if current_user.location:
        await redis_online.remove_from_online_caches(current_user)

    await redis_blacklist.drop_blacklist_cache(str(user_id))

    logger.info(f"Deleting chats of {user_id}")
    recipients = []
    # fetching only id and user ids
    chats: list[Chat] = chat_service.fetch_chat_members(user_id)
    for chat in chats:
        if user_id == chat.initiator_id:
            recipients.append(str(chat.the_other_person_id))
        elif user_id == chat.the_other_person_id:
            recipients.append(str(chat.initiator_id))
        # not relying on cascades because we need to delete images manually
        chat_service.delete_chat(chat.id)

    # if the user has no messages in global chat, send event only
    # to his chat partners
    if chat_service.has_global_chat_messages(user_id):
        # they are cascaded but let's do this manually for clarity
        chat_service.delete_global_chat_messages(user_id)
        logger.info(f"{user_id} has global messages, "
                    f"everyone will be notified")
        events.send_user_deleted_event(str(user_id))
    elif recipients:
        logger.debug(
            f"{user_id} has no global messages, "
            f"only chat partners {recipients} will be notified")
        events.send_user_deleted_event(str(user_id), recipients)

    if delete:
        user_service.delete_user(current_user)
    else:
        user_service.deactivate_user(current_user)

    logger.info("Updating popular caches")
    # repopulating popular caches
    await popular_service.populate_cache(
        country=country, city=city, gender=gender)
    await popular_service.populate_cache(country=country, city=city)

    await popular_service.populate_cache(country=country, gender=gender)
    await popular_service.populate_cache(country=country)

    await popular_service.populate_cache(gender=gender)
    await popular_service.populate_cache()

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
        user_service.delete_photo(current_user, photo_id)
    except ValueError:
        raise HTTPException(status_code=404, detail='Photo not found')

    return Response(status_code=status.HTTP_204_NO_CONTENT)
