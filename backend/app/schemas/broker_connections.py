from datetime import datetime

from pydantic import BaseModel, Field


class BrokerConnectionCreateRequest(BaseModel):
    broker_name: str = Field(min_length=1, max_length=64)
    account_label: str = Field(min_length=1, max_length=128)
    environment: str = Field(default="paper", min_length=1, max_length=16)
    connection_metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    is_active: bool = True


class BrokerConnectionUpdateRequest(BaseModel):
    broker_name: str | None = Field(default=None, min_length=1, max_length=64)
    account_label: str | None = Field(default=None, min_length=1, max_length=128)
    environment: str | None = Field(default=None, min_length=1, max_length=16)
    connection_metadata: dict[str, str | int | float | bool | None] | None = None
    is_active: bool | None = None


class BrokerConnectionResponse(BaseModel):
    id: int
    owner_user_id: int
    broker_name: str
    account_label: str
    environment: str
    connection_metadata: dict[str, str | int | float | bool | None]
    is_active: bool
    created_at: datetime
    updated_at: datetime
