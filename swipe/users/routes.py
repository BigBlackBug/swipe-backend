import re
from uuid import UUID

from fastapi import APIRouter, Depends, Body, HTTPException, UploadFile, File
from starlette import status

from . import schemas
from .models import User
from .services import UserService

IMAGE_CONTENT_TYPE_REGEXP = 'image/(png|jpe?g)'

router = APIRouter(
    prefix="/users",
    tags=["users"],
    # dependencies=[Depends(get_token_header)],
    responses={404: {"description": "Not found"}},
)


@router.get('/{user_id}', name='Get a single user',
            response_model=schemas.UserOut)
async def fetch_user(user_id: UUID,
                     user_service: UserService = Depends(UserService)):
    user = user_service.get_user(user_id)
    return user


@router.get('/', response_model=list[schemas.UserOut],
            response_model_exclude_none=True, )
async def fetch_users(user_service: UserService = Depends(UserService)):
    users = user_service.get_users()
    return users


@router.post('/', response_model=schemas.UserOut)
async def create_user(user_name: str = Body(..., embed=True),
                      user_service: UserService = Depends(UserService)):
    user = user_service.create_user(user_name)
    return user


@router.patch('/{user_id}', response_model=schemas.UserOut)
async def patch_user(user_id: UUID, user: schemas.UserIn = Body(...),
                     user_service: UserService = Depends(UserService)):
    user_object = user_service.get_user(user_id)
    if not user_object:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if user.name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail='Updating the username is prohibited')
    user_object = user_service.update_user(user_object, user)
    return user_object


@router.post("/{user_id}/photos")
async def add_photo(user_id: UUID, file: UploadFile = File(...),
                    user_service: UserService = Depends(UserService)):
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
