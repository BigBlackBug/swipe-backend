import re
from uuid import UUID

from fastapi import APIRouter, Depends, Body, HTTPException, UploadFile, File
from starlette import status
from starlette.responses import RedirectResponse

from settings import settings
from swipe import security
from . import schemas
from .models import User
from .schemas import CreateUserOut
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
    return user


@users_router.post('/', response_model=CreateUserOut,
                   status_code=status.HTTP_201_CREATED, )
async def create_user(user_payload: schemas.CreateUserIn,
                      user_service: UserService = Depends()):
    """
    Create a new user.

    This endpoint is used as a first step of registering a user.
    """
    user = user_service.create_user(user_payload)
    access_token = security.create_access_token(user_payload, user.id)

    return CreateUserOut(user_id=user.id, access_token=access_token)


# ----------------------------------------------------------------------------
@me_router.get('/', name='Get current user profile',
               response_model=schemas.UserOut)
async def fetch_user(current_user: User = Depends(security.get_current_user)):
    # TODO use a urljoin or smth
    return RedirectResponse(url=f'{users_router.prefix}/{current_user.id}')


@me_router.patch('/', response_model=schemas.UserOut)
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
    if user_body.photos:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail='Please use {user_id}/photos endpoints '
                                   'to manage photos')
    user_object = user_service.update_user(current_user, user_body)
    return user_object


@me_router.post("/photos")
async def add_photo(
        user_id: UUID,
        file: UploadFile = File(...),
        user_service: UserService = Depends(UserService),
        current_user: User = Depends(security.get_current_user)):
    """ Add a new photo to the specified user """
    user_object = user_service.get_user(user_id)
    if not user_object:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if not re.match(IMAGE_CONTENT_TYPE_REGEXP, file.content_type):
        raise HTTPException(status_code=400, detail='Unsupported image type')

    if len(user_object.photos) == User.MAX_ALLOWED_PHOTOS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f'Can not add more than {User.MAX_ALLOWED_PHOTOS} photos')

    user_service.add_photo(user_object, file.filename)

    return {"id": user_id}


@me_router.delete("/photos/{photo_index}")
async def delete_photo(
        photo_index: int,
        user_service: UserService = Depends(UserService),
        current_user: User = Depends(security.get_current_user)):
    """ Delete a user's photo """
    if photo_index > len(current_user.photos):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f'Invalid photo index '
                   f'{photo_index}>{len(current_user.photos)}')

    user_service.delete_photo(current_user, photo_index)

    return {"id": str(current_user.id)}
