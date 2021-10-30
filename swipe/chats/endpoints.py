import re
import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from starlette import status

from swipe import security
from swipe.chats.models import Chat, GlobalChatMessage
from swipe.chats.schemas import ChatOut, MultipleChatsOut, ChatORMSchema, \
    ChatMessageORMSchema
from swipe.chats.services import ChatService
from swipe.storage import storage_client
from swipe.users.models import User

router = APIRouter()

IMAGE_CONTENT_TYPE_REGEXP = 'image/(png|jpe?g)'


@router.get(
    '/global',
    name='Fetch global chat',
    response_model_exclude_none=True,
    response_model=list[ChatMessageORMSchema])
async def fetch_global_chat(
        chat_service: ChatService = Depends(),
        current_user: User = Depends(security.get_current_user)):
    chats: list[GlobalChatMessage] = chat_service.fetch_global_chat()
    return chats


@router.get(
    '/{chat_id}',
    name='Fetch a single chat',
    response_model_exclude_none=True,
    response_model=ChatOut)
async def fetch_chat(
        chat_id: UUID,
        chat_service: ChatService = Depends(),
        current_user: User = Depends(security.get_current_user)):
    chat: Chat = chat_service.fetch_chat(chat_id)
    resp_data = ChatORMSchema.parse_chat(chat, current_user.id)
    return resp_data


@router.get(
    '',
    name='Fetch all chats',
    response_model_exclude_none=True,
    response_model=MultipleChatsOut)
async def fetch_chats(chat_service: ChatService = Depends(),
                      current_user: User = Depends(security.get_current_user)):
    chats: list[Chat] = chat_service.fetch_chats(current_user)
    resp_data: MultipleChatsOut = \
        MultipleChatsOut.parse_chats(chats, current_user.id)
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
    storage_client.upload_image(image_id, file.file)
    image_url = storage_client.get_image_url(image_id)

    return {'image_id': image_id, 'image_url': image_url}
