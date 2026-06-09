from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=12000)
    conversation_id: int | None = None
    request_id: str | None = Field(default=None, min_length=1, max_length=128)


class ConversationResponse(BaseModel):
    id: int
    title: str
    created_at: str
    updated_at: str


class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    status: str
    error: str | None = None
    created_at: str
