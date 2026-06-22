from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    email: EmailStr
    display_name: str | None
    is_admin: bool
    created_at: datetime
