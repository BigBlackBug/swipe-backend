import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Body, HTTPException
from starlette import status
from starlette.responses import Response

from swipe.swipe_server.chats import schemas as chat_schemas
from swipe.swipe_server.chats.models import GlobalChatMessage
from swipe.swipe_server.chats.schemas import ChatORMSchema
from swipe.swipe_server.chats.services import ChatService
from swipe.swipe_server.misc.randomizer import RandomEntityGenerator
from swipe.swipe_server.users import schemas as user_schemas
from swipe.swipe_server.users.services.online_cache import \
    RedisOnlineUserService
from swipe.swipe_server.users.services.redis_services import \
    RedisSwipeReaperService
from swipe.swipe_server.users.services.user_service import UserService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get('/generate_user',
            tags=['misc'],
            response_model=user_schemas.UserOut)
async def generate_random_user(user_service: UserService = Depends()):
    """
    All fields are generated randomly from respective enums or within reasonable
    limits except city, which is picked from the following list:
    'Moscow', 'Saint Petersburg', 'Magadan', 'Surgut', 'Cherepovets'
    """
    randomizer = RandomEntityGenerator(user_service=user_service)
    new_user = randomizer.generate_random_user(generate_images=True)
    return user_schemas.UserOut.patched_from_orm(new_user)


@router.post('/generate_chat',
             tags=['misc'],
             response_model=chat_schemas.ChatOut,
             response_model_exclude_none=True)
async def generate_random_chat(chat_service: ChatService = Depends(),
                               user_service: UserService = Depends(),
                               user_a_id: UUID = Body(...),
                               user_b_id: UUID = Body(...),
                               n_messages: int = Body(default=10)):
    if user_a_id == user_b_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="You can't create a chat with yourself")

    user_a = user_service.get_user(user_a_id)
    if not user_a:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"User with id:{user_a_id} doesn't exist")

    user_b = user_service.get_user(user_b_id)
    if not user_b:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"User with id:{user_b_id} doesn't exist")

    randomizer = RandomEntityGenerator(chat_service=chat_service)
    chat = chat_service.fetch_chat_by_members(user_a_id, user_b_id)
    if chat:
        chat_service.delete_chat(chat.id)

    chat = randomizer.generate_random_chat(
        user_a=user_a, user_b=user_b,
        n_messages=n_messages, generate_images=True
    )

    resp_data = ChatORMSchema.parse_chat(chat, user_a_id)
    return resp_data


@router.post('/generate_global_chat',
             tags=['misc'],
             response_model=list[chat_schemas.ChatMessageORMSchema],
             response_model_exclude_none=True)
async def generate_global_chat(chat_service: ChatService = Depends(),
                               n_messages: int = Body(default=10, embed=True)):
    randomizer = RandomEntityGenerator(chat_service=chat_service)
    chat_messages: list[GlobalChatMessage] = \
        randomizer.generate_random_global_chat(n_messages=n_messages)

    return chat_messages


@router.post(
    "/auth",
    tags=['auth'],
    responses={
        200: {
            "description": "An existing user has been authenticated",
            "model": user_schemas.AuthenticationOut
        },
        201: {
            "description": "A new user has been created",
            "model": user_schemas.AuthenticationOut
        }
    })
async def authenticate_user(auth_payload: user_schemas.AuthenticationIn,
                            response: Response,
                            user_service: UserService = Depends(),
                            redis_online: RedisOnlineUserService = Depends(),
                            redis_swipe: RedisSwipeReaperService = Depends()):
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
        await redis_swipe.reset_swipe_reap_timestamp(user.id)

    await redis_online.save_auth_token(str(user.id), new_token)
    return user_schemas.AuthenticationOut(
        user_id=user.id, access_token=new_token)
