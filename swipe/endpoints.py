import logging

from fastapi import APIRouter, Depends
from starlette import status
from starlette.responses import Response

from swipe.users import schemas
from swipe.users.services import UserService, RedisService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/auth",
    tags=['auth'],
    responses={
        200: {
            "description": "An existing user has been authenticated",
            "model": schemas.AuthenticationOut
        },
        201: {
            "description": "A new user has been created",
            "model": schemas.AuthenticationOut
        }
    })
async def authenticate_user(auth_payload: schemas.AuthenticationIn,
                            response: Response,
                            user_service: UserService = Depends(),
                            redis_service: RedisService = Depends()):
    """
    Returns a jwt access token either for an existing user
    or for a new one, in case no match has been found for the supplied
    auth_provider and the provider_user_id
    """
    user = user_service.find_user_by_auth(auth_payload)

    if user:
        # user is logging in from a new phone
        # create new token and invalidate the old one
        logger.info(f"Found a user id:{auth_payload.provider_user_id}, "
                    f"generating a new token")
        new_token = user_service.create_access_token(user, auth_payload)

        response.status_code = status.HTTP_200_OK
    else:
        logger.info(
            f"Unable to find a user id:'{auth_payload.provider_user_id}' "
            f"authorized with '{auth_payload.auth_provider}', creating a user")
        user = user_service.create_user(auth_payload)
        new_token = user_service.create_access_token(user, auth_payload)

        response.status_code = status.HTTP_201_CREATED

    await redis_service.reset_swipe_reap_timestamp(user)
    return schemas.AuthenticationOut(
        user_id=user.id, access_token=new_token)


@router.get('/generate_user',
            tags=['misc'],
            response_model=schemas.UserOut)
async def generate_random_user(user_service: UserService = Depends()):
    new_user = user_service.generate_random_user(generate_images=True)
    return schemas.UserOut.patched_from_orm(new_user)
