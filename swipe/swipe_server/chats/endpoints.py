import logging
import re
import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Body
from sqlalchemy.engine import Row
from starlette import status
from starlette.responses import Response

from swipe.swipe_server.misc import security
from swipe.swipe_server.chats.models import Chat, GlobalChatMessage
from swipe.swipe_server.chats.schemas import ChatOut, MultipleChatsOut, \
    ChatORMSchema, GlobalChatOut
from swipe.swipe_server.chats.services import ChatService
from swipe.swipe_server.misc.storage import storage_client
from swipe.swipe_server.users.models import User
from swipe.swipe_server.users.services import UserService

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
        current_user: User = Depends(security.get_current_user)):
    chats: list[GlobalChatMessage] = \
        chat_service.fetch_global_chat(last_message_id)
    users: list[Row] = \
        user_service.get_global_chat_preview([chat.sender_id for chat in chats])
    return GlobalChatOut.parse_chats(chats, users)


@router.delete(
    '/images',
    name='Deletes chat images',
    responses={
        204: {
            "description": "Images successfully deleted",
        },
    },
    status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat_image(
        image_ids: list[str] = Body(..., embed=True),
        current_user: User = Depends(security.get_current_user)):
    for image_id in image_ids:
        storage_client.delete_chat_image(image_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    '/{chat_id}',
    name='Fetch a single chat',
    response_model_exclude_none=True,
    response_model=ChatOut)
async def fetch_chat(
        chat_id: UUID,
        only_unread: bool = False,
        chat_service: ChatService = Depends(),
        current_user: User = Depends(security.get_current_user)):
    chat: Chat = chat_service.fetch_chat(chat_id, only_unread)
    resp_data = ChatORMSchema.parse_chat(chat, current_user.id)
    return resp_data


@router.get(
    '',
    name='Fetch all chats',
    response_model_exclude_none=True,
    response_model=MultipleChatsOut)
async def fetch_chats(
        only_unread: bool = False,
        chat_service: ChatService = Depends(),
        user_service: UserService = Depends(),
        current_user: User = Depends(security.get_current_user)):
    """
    When 'only_unread' is set to true, returns only chats with unread messages
    """
    chats: list[Chat] = chat_service.fetch_chats(current_user.id, only_unread)
    user_ids = set()
    for chat in chats:
        user_ids.add(chat.initiator_id)
        user_ids.add(chat.the_other_person_id)

    users: list[Row] = \
        user_service.get_user_chat_preview(list(user_ids), location=True)
    resp_data: MultipleChatsOut = \
        MultipleChatsOut.parse_chats(chats, users, current_user.id)
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
        current_user: User = Depends(security.get_current_user)):
    if not current_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if not re.match(IMAGE_CONTENT_TYPE_REGEXP, file.content_type):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Unsupported image type')

    _, _, extension = file.content_type.partition('/')

    image_id = f'{uuid.uuid4()}.{extension}'
    storage_client.upload_chat_image(image_id, file.file)
    image_url = storage_client.get_chat_image_url(image_id)

    return {'image_id': image_id, 'image_url': image_url}