from typing import Optional
from pydantic import BaseModel, field_validator


class BotConfigCreate(BaseModel):
    region: str
    name: str
    description: Optional[str] = None

    @field_validator("description")
    @classmethod
    def validate_description(cls, v):
        if v is not None and len(v) > 120:
            raise ValueError("Описание не должно превышать 120 символов")
        return v


class BotConfigResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    region: str
    name: str
    description: Optional[str]