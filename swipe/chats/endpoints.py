from uuid import UUID

from fastapi import APIRouter, Depends

from swipe import security
from swipe.chats.models import Chat
from swipe.chats.schemas import ChatOut, MultipleChatsOut, ChatORMSchema
from swipe.chats.services import ChatService
from swipe.users.models import User

router = APIRouter(tags=['chats'])


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
