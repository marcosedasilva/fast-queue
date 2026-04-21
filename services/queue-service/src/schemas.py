from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from .models import QueueStatus 

class QueueCreate(BaseModel):
    title: str
    entry_fee: int
    max_slots: int = 10

class QueueUpdate(BaseModel):
    title: Optional[str] = None
    max_slots: Optional[int] = None
    status: Optional[QueueStatus] = None

class QueueResponse(BaseModel):
    id: int
    title: str
    entry_fee: float
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class QueueJoin(BaseModel):
    game_nick: str
    social_handle: Optional[str] = None

class QueueEntryResponse(BaseModel):
    id: int
    queue_id: int
    position: int
    status: str

    model_config = ConfigDict(from_attributes=True)

class CalledViewerResponse(BaseModel):
    id: int
    viewer_id: str
    display_name: Optional[str] = None
    position: int
    status: str

    model_config = ConfigDict(from_attributes=True)

class UserUpdate(BaseModel):
    display_name: str

class UserResponse(BaseModel):
    id: str
    email: str
    display_name: Optional[str] = None
    wallet_balance: float

    model_config = ConfigDict(from_attributes=True)

class QueueJoinResponse(BaseModel):
    id: str
    amount: int
    status: str
    brCode: str
    brCodeBase64: str
    expiresAt: str