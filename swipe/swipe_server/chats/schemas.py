from __future__ import annotations

import datetime
from typing import Optional, Any
from uuid import UUID

from pydantic import BaseModel, validator
from sqlalchemy.engine import Row

from swipe.swipe_server.chats.models import MessageStatus, ChatMessage, Chat, ChatStatus, \
    ChatSource, GlobalChatMessage
from swipe.swipe_server.misc.storage import storage_client
from swipe.swipe_server.users.models import User
from swipe.swipe_server.users.schemas import UserOutGlobalChatPreviewORM, \
    UserOutChatPreview


class ChatMessageORMSchema(BaseModel):
    id: UUID
    timestamp: datetime.datetime
    status: Optional[MessageStatus] = None
    message: Optional[str] = None
    image_id: Optional[str] = None
    image_url: Optional[str] = None

    is_liked: Optional[bool] = None
    sender_id: UUID

    @classmethod
    def patched_from_orm(cls: ChatMessageORMSchema,
                         obj: Any) -> ChatMessageORMSchema:
        schema_obj: ChatMessageORMSchema = cls.from_orm(obj)
        if schema_obj.image_id:
            schema_obj.image_url = \
                storage_client.get_chat_image_url(schema_obj.image_id)
        return schema_obj

    class Config:
        orm_mode = True


class GlobalChatOut(BaseModel):
    messages: list[ChatMessageORMSchema] = []
    users: dict[UUID, UserOutGlobalChatPreviewORM] = {}

    @classmethod
    def parse_chats(cls, messages: list[GlobalChatMessage],
                    users: list[User] | list[Row]):
        result = {'messages': [], 'users': {}}
        for message in messages:
            result['messages'].append(
                ChatMessageORMSchema.patched_from_orm(message))
        for user in users:
            user_schema = UserOutGlobalChatPreviewORM.from_orm(user)
            result['users'][user.id] = user_schema
        return cls.parse_obj(result)


class ChatORMSchema(BaseModel):
    id: UUID
    the_other_person_id: Optional[UUID] = None
    initiator_id: Optional[UUID] = None
    messages: list[ChatMessageORMSchema] = []
    creation_date: datetime.datetime
    source: ChatSource
    status: ChatStatus

    @validator("messages", pre=True, each_item=True)
    def patch_message(cls, message: ChatMessage, values: dict[str, Any]):
        return ChatMessageORMSchema.patched_from_orm(message)

    @classmethod
    def parse_chat(cls, chat: Chat, current_user_id: UUID) -> dict[str, Any]:
        schema_obj = cls.from_orm(chat)
        chat_dict = schema_obj.dict()
        if chat_dict['the_other_person_id'] == current_user_id:
            chat_dict['the_other_person_id'] = chat_dict['initiator_id']
            del chat_dict['initiator_id']
        return chat_dict

    class Config:
        orm_mode = True


# this duplicate model is required for fastapi endpoints
# because the ChatORMSchema doesn't work with openapi because of orm_mode
class ChatOut(BaseModel):
    id: UUID
    the_other_person_id: Optional[UUID] = None
    initiator_id: Optional[UUID] = None
    messages: list[ChatMessageORMSchema] = []
    source: ChatSource
    status: ChatStatus
    creation_date: datetime.datetime


class MultipleChatsOut(BaseModel):
    requests: list[ChatOut] = []
    chats: list[ChatOut] = []
    users: dict[UUID, UserOutChatPreview] = {}

    @classmethod
    def parse_chats(cls, chats: list[Chat],
                    users: list[User] | list[Row],
                    current_user_id: UUID) -> MultipleChatsOut:
        result = {'chats': [], 'requests': [], 'users': {}}

        for chat in chats:
            data = ChatORMSchema.parse_chat(chat, current_user_id)

            if chat.status == ChatStatus.ACCEPTED:
                result['chats'].append(data)
            else:
                # opened chats are still requested
                result['requests'].append(data)

        for user in users:
            user_dict: UserOutChatPreview \
                = UserOutChatPreview.patched_from_orm(user)
            result['users'][user.id] = user_dict
        return cls.parse_obj(result)