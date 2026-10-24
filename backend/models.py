from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .hazards import KINDS

Priority = Literal['normal', 'urgent']
HazardKind = Literal[tuple(KINDS)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class OrderIn(StrictModel):
    pickup: str = Field(min_length=1, max_length=12)
    dropoff: str = Field(min_length=1, max_length=12)
    priority: Priority = 'normal'


Role = Literal['pickup', 'dropoff']


class PlaceIn(StrictModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    name: str = Field(min_length=1, max_length=40)
    role: Role


class PlaceUpdate(StrictModel):
    name: str | None = Field(None, min_length=1, max_length=40)
    role: Role | None = None


class WaypointIn(StrictModel):
    place: str | None = Field(None, max_length=12)     # an existing point, or
    lat: float | None = Field(None, ge=-90, le=90)      # a spot clicked on the map
    lon: float | None = Field(None, ge=-180, le=180)
    name: str = Field('', max_length=40)


class MissionIn(StrictModel):
    waypoints: list[WaypointIn] = Field(min_length=1, max_length=20)


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
