from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Values(StrictModel):
    temperature_c: float = Field(ge=0, le=6553.5)
    running: bool
    setpoint_c: float = Field(ge=0, le=6553.5)


class Result(StrictModel):
    id: str = Field(max_length=36)
    status: Literal["applied", "rejected", "failed_or_unknown"]


class Exchange(StrictModel):
    values: Values | None = None
    quality: Literal["good", "unavailable"]
    writable: bool = False
    result: Result | None = None


class Setpoint(StrictModel):
    value: int = Field(strict=True, ge=15, le=35)
