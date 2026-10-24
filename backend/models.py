from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .hazards import KINDS

Priority = Literal['normal', 'urgent']
HazardKind = Literal[tuple(KINDS)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class OrderIn(StrictModel):
    pickup: str = Field(pattern=r'^P\d+$')
    dropoff: str = Field(pattern=r'^D\d+$')
    priority: Priority = 'normal'


class PriorityIn(StrictModel):
    priority: Priority


class HazardIn(StrictModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    kind: HazardKind
    announced: bool = False


class SpeedIn(StrictModel):
    speed: int = Field(ge=1, le=30)


class BatteryIn(StrictModel):
    level: float = Field(ge=0, le=100)


class Chat(StrictModel):
    message: str = Field(min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    available: bool
    message: str
    applied: bool = False
    model: str | None = None
