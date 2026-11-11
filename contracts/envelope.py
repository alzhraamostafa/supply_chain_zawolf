"""Shared wrapper for every component output (source, confidence, human review)."""
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

Component = Literal[
    "demand_forecast",
    "inventory_optimizer",
    "supplier_intelligence",
    "procurement_agent",
    "quote_analysis",
    "risk_engine",
    "negotiation_agent",
    "delivery_agent",
    "executive_copilot",
]


class OutputEnvelope(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    component: Component
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    autonomy_level: int = Field(default=0, ge=0, le=2)
    requires_human_approval: bool = True
    assumptions: list[str] = Field(default_factory=list)
    payload: dict[str, Any]

    @model_validator(mode="after")
    def low_autonomy_needs_approval(self):
        if self.autonomy_level < 2 and not self.requires_human_approval:
            raise ValueError("autonomy levels 0 and 1 must require human approval")
        return self