from typing import Optional
from pydantic import BaseModel, field_validator


class GlobalConfigRegionSchema(BaseModel):
    region: str
    name: str
    description: Optional[str] = None

    @field_validator("description")
    @classmethod
    def validate_description(cls, v):
        if v is not None and len(v) > 120:
            raise ValueError("Описание не должно превышать 120 символов")
        return v


class GlobalConfigCreate(BaseModel):
    name: str


class GlobalConfigUpdate(BaseModel):
    name: Optional[str] = None
    welcome_text: Optional[str] = None
    welcome_buttons: Optional[list] = None
    auto_reply_text: Optional[str] = None


class GlobalConfigRegionCreate(BaseModel):
    region: str
    name: str
    description: Optional[str] = None

    @field_validator("description")
    @classmethod
    def validate_description(cls, v):
        if v is not None and len(v) > 120:
            raise ValueError("Описание не должно превышать 120 символов")
        return v


class GlobalConfigResponse(BaseModel):
    id: int
    name: str
    avatar_path: Optional[str] = None
    welcome_text: Optional[str] = None
    welcome_photo_path: Optional[str] = None
    welcome_buttons: Optional[list] = None
    auto_reply_text: Optional[str] = None
    is_active: bool
    regions: list[GlobalConfigRegionSchema] = []

    class Config:
        from_attributes = True
