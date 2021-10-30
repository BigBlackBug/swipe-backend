from __future__ import annotations

import datetime
from typing import Optional, Any
from uuid import UUID

from pydantic import BaseModel, validator

from swipe.chats.models import MessageStatus, ChatMessage, Chat, ChatStatus
from swipe.storage import CloudStorage


class ChatMessageORMSchema(BaseModel):
    id: UUID
    timestamp: datetime.datetime
    status: Optional[MessageStatus] = None
    message: Optional[str] = None
    image_id: Optional[str] = None
    image_url: Optional[str] = None

    sender_id: UUID

    @classmethod
    def patched_from_orm(cls: ChatMessageORMSchema,
                         obj: Any) -> ChatMessageORMSchema:
        schema_obj: ChatMessageORMSchema = cls.from_orm(obj)
        storage = CloudStorage()
        if schema_obj.image_id:
            schema_obj.image_url = storage.get_image_url(schema_obj.image_id)
        return schema_obj

    class Config:
        orm_mode = True


class ChatORMSchema(BaseModel):
    the_other_person_id: Optional[UUID] = None
    initiator_id: Optional[UUID] = None
    messages: list[ChatMessageORMSchema] = []

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


# this duplicate model is required because the first one with orm_mode=True
# doesn't work with openapi
class ChatOut(BaseModel):
    the_other_person_id: Optional[UUID] = None
    initiator_id: Optional[UUID] = None
    messages: list[ChatMessageORMSchema] = []


class MultipleChatsOut(BaseModel):
    requests: list[ChatOut] = []
    chats: list[ChatOut] = []

    @classmethod
    def parse_chats(cls, chats: list[Chat],
                    current_user_id: UUID) -> MultipleChatsOut:
        result = {'chats': [], 'requests': []}

        for chat in chats:
            data = ChatORMSchema.parse_chat(chat, current_user_id)

            if chat.status == ChatStatus.REQUESTED:
                result['requests'].append(data)
            else:
                result['chats'].append(data)
        return cls.parse_obj(result)
