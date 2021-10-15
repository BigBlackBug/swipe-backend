import re
from uuid import UUID

from fastapi import APIRouter, Depends, Body, HTTPException, UploadFile, File
from starlette import status
from starlette.responses import RedirectResponse

from settings import settings
from swipe import security
from . import schemas
from .models import User
from .services import UserService

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


@users_router.get('/{user_id}', name='Get a single user',
                  response_model=schemas.UserOut)
async def fetch_user(
        user_id: UUID,
        user_service: UserService = Depends(),
        current_user: User = Depends(security.get_current_user)):
    user = user_service.get_user(user_id)
    user_out: schemas.UserOut = schemas.UserOut.patched_from_orm(user)
    return user_out


# ----------------------------------------------------------------------------
@me_router.get('/', name='Get current user profile',
               response_model=schemas.UserOut)
async def fetch_user(current_user: User = Depends(security.get_current_user)):
    user_out: schemas.UserOut = schemas.UserOut.patched_from_orm(current_user)
    return user_out


@me_router.patch('/',
                 response_model=schemas.UserOut,
                 response_model_exclude={'photos', })
async def patch_user(
        user_body: schemas.UserIn = Body(...),
        user_service: UserService = Depends(),
        current_user: User = Depends(security.get_current_user)):
    """
    Update a current user's fields
    """
    if user_body.name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail='Updating the username is prohibited')

    user_object = user_service.update_user(current_user, user_body)
    return user_object


@me_router.post("/photos", status_code=status.HTTP_201_CREATED)
async def add_photo(
        file: UploadFile = File(...),
        user_service: UserService = Depends(UserService),
        current_user: User = Depends(security.get_current_user)):
    """ Add a new photo to the specified user """
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


@me_router.delete("/photos/{photo_id}")
async def delete_photo(
        photo_id: UUID,
        user_service: UserService = Depends(UserService),
        current_user: User = Depends(security.get_current_user)):
    """ Delete a user's photo """
    user_service.delete_photo(current_user, photo_id)

    return {"id": str(current_user.id)}
