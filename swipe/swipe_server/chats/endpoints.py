import logging
import re
import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.engine import Row
from starlette import status

from swipe.swipe_server.chats.models import Chat, GlobalChatMessage
from swipe.swipe_server.chats.schemas import ChatOut, MultipleChatsOut, \
    ChatORMSchema, GlobalChatOut
from swipe.swipe_server.chats.services import ChatService
from swipe.swipe_server.misc import security
from swipe.swipe_server.misc.storage import storage_client
from swipe.swipe_server.users.models import User
from swipe.swipe_server.users.services.user_service import UserService

router = APIRouter()

IMAGE_CONTENT_TYPE_REGEXP = 'image/(png|jpe?g)'

logger = logging.getLogger(__name__)


@router.get(
    '/global',
    name='Fetch global chat',
    response_model_exclude_none=True,
    response_model=GlobalChatOut)
async def fetch_global_chat(
        last_message_id: UUID = None,
        chat_service: ChatService = Depends(),
        user_service: UserService = Depends(),
        user_id: UUID = Depends(security.auth_user_id)):
    messages: list[GlobalChatMessage] = \
        chat_service.fetch_global_chat(last_message_id)
    users: list[User] = \
        user_service.get_global_chat_preview([
            message.sender_id for message in messages
        ])
    return GlobalChatOut.parse_chats(messages, users)


@router.get(
    '/{chat_id}',
    name='Fetch a single chat',
    response_model_exclude_none=True,
    response_model=ChatOut,
    deprecated=True)
async def fetch_chat(
        chat_id: UUID,
        only_unread: bool = False,
        chat_service: ChatService = Depends(),
        user_id: UUID = Depends(security.auth_user_id)):
    chat: Chat = chat_service.fetch_chat(chat_id, only_unread)
    resp_data = ChatORMSchema.parse_chat(chat, user_id)
    return resp_data


@router.get(
    '',
    name='Fetch all chats',
    response_model=MultipleChatsOut)
async def fetch_chats(
        only_unread: bool = False,
        chat_service: ChatService = Depends(),
        user_service: UserService = Depends(),
        user_id: UUID = Depends(security.auth_user_id)):
    """
    When 'only_unread' is set to true, returns only chats with unread messages
    """
    chats: list[Chat] = chat_service.fetch_chats(user_id, only_unread)
    user_ids = set()
    for chat in chats:
        user_ids.add(chat.initiator_id)
        user_ids.add(chat.the_other_person_id)

    users: list[User] = \
        user_service.get_user_chat_preview(list(user_ids))

    # user needs to know the list of all chats in case some were deleted
    # while he's offline
    chat_ids: list[UUID] = chat_service.fetch_chat_ids(user_id)

    logger.info(f"Got {len(chats)} chats, total chats {len(chat_ids)}")
    resp_data: MultipleChatsOut = \
        await MultipleChatsOut.parse_chats(chats, chat_ids, users, user_id)
    return resp_data


@router.post(
    '/images',
    name='Upload an image for chat',
    responses={
        201: {
            "description": "Uploaded image data",
            "content": {
                "application/json": {
                    "example": {
                        "image_id": "", "image_url": ""
                    }
                }
            },
        },
    },
    status_code=status.HTTP_201_CREATED)
async def upload_image(
        file: UploadFile = File(...),
        user_id: UUID = Depends(security.auth_user_id)):
    if not re.match(IMAGE_CONTENT_TYPE_REGEXP, file.content_type):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Unsupported image type')

    _, _, extension = file.content_type.partition('/')

    image_id = f'{uuid.uuid4()}.{extension}'
    storage_client.upload_chat_image(image_id, file.file)
    image_url = storage_client.get_chat_image_url(image_id)

    return {'image_id': image_id, 'image_url': image_url}
