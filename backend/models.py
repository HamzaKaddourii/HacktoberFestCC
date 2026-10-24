from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

Station = Literal['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J']


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Delivery(StrictModel):
    station: Station
    priority: Literal['normal', 'urgent'] = 'normal'


class Obstacle(StrictModel):
    cell: tuple[int, int]
    blocked: bool = True


class Corridor(StrictModel):
    corridor: Literal['A-C'] = 'A-C'
    blocked: bool = True


class Chat(StrictModel):
    message: str = Field(min_length=1, max_length=2000)


class Order(StrictModel):
    before: Station
    after: Station


class AIInstructions(StrictModel):
    explanation: str = Field(max_length=3000)
    deliveries: list[Delivery] = Field(default_factory=list, max_length=10)
    obstacles: list[Obstacle] = Field(default_factory=list, max_length=20)
    corridors: list[Corridor] = Field(default_factory=list, max_length=1)
    precedence: list[Order] = Field(default_factory=list, max_length=10)


class ChatResponse(BaseModel):
    available: bool
    message: str
    applied: bool = False
    model: str | None = None


class DeliveryState(Delivery):
    status: Literal['pending', 'completed']


class Analytics(BaseModel):
    completed: int
    pending: int
    distance: int
    remaining: int
    eta: float
    baseline: int
    optimized: int
    replans: int
    reduction: float
    progress: int


class AnalyticsResponse(Analytics):
    battery: float


class Event(BaseModel):
    id: int
    time: str
    title: str
    detail: str
    kind: str


class Comparison(BaseModel):
    before: int
    after: int
    reason: str


class AIStatus(BaseModel):
    available: bool
    model: str
    reason: str


class StateResponse(BaseModel):
    position: tuple[int, int]
    trail: list[tuple[int, int]]
    battery: float
    status: Literal['idle', 'ready', 'running', 'paused', 'blocked', 'charging', 'completed']
    deliveries: list[DeliveryState]
    obstacles: list[tuple[int, int]]
    path: list[tuple[int, int]]
    order: list[str]
    events: list[Event]
    comparison: Comparison | None
    unreachable: list[str]
    analytics: Analytics
    ai: AIStatus


class MapResponse(BaseModel):
    width: int
    height: int
    walls: list[tuple[int, int]]
    shelves: list[tuple[int, int, int, int]]
    stations: dict[str, tuple[int, int]]
    base: tuple[int, int]
    corridors: dict[str, list[tuple[int, int]]]
    metres_per_cell: int
    seconds_per_step: float
