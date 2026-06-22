from datetime import datetime

from pydantic import BaseModel, Field


class StrategyCombinationCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    strategies: list[str] = Field(min_length=1, max_length=20)
    is_shared: bool = True


class StrategyCombinationUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    strategies: list[str] | None = Field(default=None, min_length=1, max_length=20)
    is_shared: bool | None = None


class StrategyCombinationResponse(BaseModel):
    id: int
    owner_user_id: int
    owner_email: str
    cloned_from_id: int | None
    name: str
    description: str | None
    strategies: list[str]
    is_shared: bool
    created_at: datetime
    updated_at: datetime
