"""Contract for the demand_forecast component: what goes in, what comes out."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .envelope import OutputEnvelope

Level = Literal["family", "brand", "sku"]


class ForecastRequest(BaseModel):
    level: Level
    horizon_weeks: int = Field(default=1, ge=1, le=12)
    series_ids: list[str] | None = None   # None = all series at that level


class ForecastPoint(BaseModel):
    series_id: str
    week_start: date
    p50: float = Field(ge=0)
    p10: float | None = Field(default=None, ge=0)
    p90: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def quantiles_in_order(self):
        if self.p10 is not None and self.p10 > self.p50:
            raise ValueError("p10 must be <= p50")
        if self.p90 is not None and self.p90 < self.p50:
            raise ValueError("p90 must be >= p50")
        return self


class ForecastPayload(BaseModel):
    level: Level
    horizon_weeks: int = Field(ge=1, le=12)
    algorithm: str
    unit: Literal["pcs"] = "pcs"
    forecasts: list[ForecastPoint] = Field(min_length=1)
    backtest_wape: float | None = Field(default=None, ge=0)


def to_envelope(payload: ForecastPayload, source: list[str], confidence: float) -> OutputEnvelope:
    return OutputEnvelope(
        component="demand_forecast",
        source=source,
        confidence=confidence,
        payload=payload.model_dump(mode="json"),
    )