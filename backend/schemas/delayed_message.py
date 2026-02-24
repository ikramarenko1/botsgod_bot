from typing import Optional, List
from pydantic import BaseModel

class DelayedConfigRequest(BaseModel):
    text: Optional[str] = None
    buttons: Optional[List[dict]] = None
    delay_minutes: Optional[int] = None