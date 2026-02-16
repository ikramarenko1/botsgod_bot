from typing import Optional
from pydantic import BaseModel

class DelayedConfigRequest(BaseModel):
    text: str
    delay_minutes: int
    buttons: Optional[list] = None