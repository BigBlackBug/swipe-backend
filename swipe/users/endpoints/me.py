import logging
import re

from fastapi import Depends, Body, HTTPException, UploadFile, File, APIRouter
from starlette import status
from starlette.responses import Response

from swipe import security
from swipe.users import schemas
from swipe.users.models import User
from swipe.users.services import UserService, RedisService

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


@router.patch(
    '',
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
    user_object = user_service.update_user(current_user, user_body)
    return user_object


@router.post(
    '/photos',
    name='Add a photo to the authenticated user',
    responses={
        200: {
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

    photo_id = user_service.add_photo(current_user, file.file, extension)
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


@router.post(
    '/online',
    name='Refresh the online status',
    status_code=status.HTTP_204_NO_CONTENT)
async def refresh_online_status(
        current_user: User = Depends(security.get_current_user),
        redis_service: RedisService = Depends()
):
    await redis_service.refresh_online_status(current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
