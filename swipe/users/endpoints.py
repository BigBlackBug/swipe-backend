import logging
import re
import time
from uuid import UUID

from fastapi import APIRouter, Depends, Body, HTTPException, UploadFile, File
from starlette import status
from starlette.responses import Response

from settings import settings, constants
from swipe import security
from . import schemas
from .models import User
from .services import UserService, RedisService

IMAGE_CONTENT_TYPE_REGEXP = 'image/(png|jpe?g)'

users_router = APIRouter(
    prefix=f"{settings.API_V1_PREFIX}/users",
    tags=["users"],
    responses={404: {"description": "Not found"}},
)
me_router = APIRouter(
    prefix=f"{settings.API_V1_PREFIX}/me",
    tags=["me"],
    responses={404: {"description": "Not found"}},
)

logger = logging.getLogger(__name__)


@users_router.get('/{user_id}',
                  name='Get a single user',
                  response_model=schemas.UserOut)
async def fetch_user(
        user_id: UUID,
        user_service: UserService = Depends(),
        current_user: User = Depends(security.get_current_user)):
    user = user_service.get_user(user_id)
    user_out: schemas.UserOut = schemas.UserOut.patched_from_orm(user)
    return user_out


# ----------------------------------------------------------------------------
@me_router.get('/',
               name="Get current users profile",
               response_model=schemas.UserOut)
async def fetch_user(current_user: User = Depends(security.get_current_user)):
    user_out: schemas.UserOut = schemas.UserOut.patched_from_orm(current_user)
    return user_out


@me_router.patch('/',
                 name="Update the authenticated users fields",
                 response_model=schemas.UserOut,
                 response_model_exclude={'photo_urls', })
async def patch_user(
        user_body: schemas.UserUpdate = Body(...),
        user_service: UserService = Depends(),
        current_user: User = Depends(security.get_current_user)):
    # TODO This is bs, this field should not be in the docs
    # but the solutions are ugly AF
    # https://github.com/tiangolo/fastapi/issues/1357
    if user_body.zodiac_sign:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='zodiac_sign is updated whenever birth_date is updated')

    user_object = user_service.update_user(current_user, user_body)
    return user_object


@me_router.post("/photos",
                name='Add a photo to the authenticated user',
                status_code=status.HTTP_201_CREATED)
async def add_photo(
        file: UploadFile = File(...),
        user_service: UserService = Depends(UserService),
        current_user: User = Depends(security.get_current_user)):
    if not current_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if not re.match(IMAGE_CONTENT_TYPE_REGEXP, file.content_type):
        raise HTTPException(status_code=400, detail='Unsupported image type')

    if len(current_user.photos) == User.MAX_ALLOWED_PHOTOS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f'Can not add more than {User.MAX_ALLOWED_PHOTOS} photos')

    image_id = user_service.add_photo(current_user, file)

    return {'image_id': image_id}


@me_router.delete("/photos/{photo_id}",
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


@me_router.get(
    "/swipes/status",
    name='Returns timestamp for when the free swipes can be reaped',
    responses={
        200: {
            'description': '',
            "content": {
                "application/json": {
                    "example": {
                        "reap_timestamp": 1500
                    }
                }
            },
        }
    })
async def get_free_swipe_status(
        current_user: User = Depends(security.get_current_user),
        redis_service: RedisService = Depends()):
    reap_timestamp = await redis_service.get_swipe_reap_timestamp(current_user)
    if not reap_timestamp:
        logger.warning(f"No reap timestamp found. Resetting the timestamp")
        reap_timestamp = await redis_service.reset_swipe_reap_timestamp(
            current_user)

    return {
        'reap_timestamp': reap_timestamp
    }


@me_router.post(
    "/swipes/reap",
    name='Reap free swipes',
    responses={
        409: {
            'description': 'Free swipes are not available at the moment'
        },
        200: {
            'description': 'Returns the current amount of swipes and the '
                           'timestamp when new swipes can be reaped',
            "content": {
                "application/json": {
                    "example": {
                        "swipes": "100500",
                        "reap_timestamp": 1500
                    }
                }
            },
        }
    })
async def get_free_swipes(
        current_user: User = Depends(security.get_current_user),
        user_service: UserService = Depends(UserService),
        redis_service: RedisService = Depends()):
    reap_timestamp: int = await redis_service.get_swipe_reap_timestamp(
        current_user)

    if reap_timestamp:
        if (diff := reap_timestamp - int(time.time())) > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Free swipes will be available "
                       f"in {diff} seconds")

        current_user = user_service.add_swipes(
            current_user, constants.FREE_SWIPES_PER_TIME_PERIOD)
        reap_timestamp = \
            await redis_service.reset_swipe_reap_timestamp(current_user)
    else:
        logger.warning(f"No reap timestamp found. Resetting the timestamp")
        reap_timestamp = await redis_service.reset_swipe_reap_timestamp(
            current_user)

    return {
        'swipes': current_user.swipes,
        'reap_timestamp': reap_timestamp
    }


@me_router.post("/swipes",
                name='Add swipes',
                status_code=status.HTTP_201_CREATED)
async def add_swipes(
        swipes: int = Body(...),
        reason: str = Body(...),
        current_user: User = Depends(security.get_current_user),
        user_service: UserService = Depends(UserService)
):
    user_service.add_swipes(current_user, swipes)
    logger.info(f'{swipes} swipes have been added. Reason {reason}')
    return Response(status_code=status.HTTP_201_CREATED)
