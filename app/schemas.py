from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=12000)
    conversation_id: int | None = None
    request_id: str | None = Field(default=None, min_length=1, max_length=128)
    model: str | None = Field(default=None, min_length=1, max_length=256)
    attachment_ids: list[int] | None = None


class ConversationResponse(BaseModel):
    id: int
    title: str
    model: str | None = None
    created_at: str
    updated_at: str


class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    status: str
    error: str | None = None
    created_at: str


class AttachmentResponse(BaseModel):
    id: int
    filename: str
    content_type: str
    created_at: str
