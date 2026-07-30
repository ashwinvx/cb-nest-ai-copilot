from typing import Literal

from pydantic import BaseModel, Field


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatActionsRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=40)


class ChatActionConfirmRequest(BaseModel):
    action_token: str = Field(min_length=10, max_length=4000)
    approve: bool = True


class ChatSessionCreate(BaseModel):
    title: str = Field(min_length=3, max_length=120)


class ChatMessageCreate(BaseModel):
    role: str = Field(min_length=3, max_length=20)
    content: str = Field(min_length=1, max_length=4000)
