import logging

from fastapi import APIRouter, Depends
from starlette import status
from starlette.responses import Response

from settings import settings
from swipe.users import schemas
from swipe.users.services import UserService

router = APIRouter(prefix=f'{settings.API_V1_PREFIX}', tags=['misc'])
logger = logging.getLogger(__name__)


# TODO docs for different status codes
@router.post("/auth", response_model=schemas.AuthenticationOut)
async def authenticate_user(user_payload: schemas.AuthenticationIn,
                            response: Response,
                            user_service: UserService = Depends()):
    user = user_service.find_user_by_auth(user_payload)

    if user:
        # user is logging in from a new phone
        # create new token and invalidate the old one
        logger.info(f"Found a user id:{user_payload.provider_user_id}, "
                    f"generating a new token")
        new_token = user_service.create_access_token(user, user_payload)

        response.status_code = status.HTTP_200_OK
        return schemas.AuthenticationOut(user_id=user.id, access_token=new_token)
    else:
        logger.info(
            f"Unable to find a user id:'{user_payload.provider_user_id}' "
            f"authorized with '{user_payload.auth_provider}', creating a user")
        user = user_service.create_user(user_payload)
        new_token = user_service.create_access_token(user, user_payload)

        response.status_code = status.HTTP_201_CREATED
        return schemas.AuthenticationOut(user_id=user.id, access_token=new_token)
