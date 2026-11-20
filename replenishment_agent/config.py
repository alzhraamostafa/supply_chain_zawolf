"""Settings for the replenishment agent."""
import json, os
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))

def _load(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}

@dataclass
class Config:
    db_path: str
    environment: str = "replenishment_demo"
    as_of: str | None = None            # None = last order date in the data
    agent_actor: str = "replenishment_agent"
    policy: dict = field(default_factory=lambda: _load("policy.json"))
    aliases: dict = field(default_factory=lambda: _load("material_aliases.json"))

    def approval_role(self, total_egp: float) -> str:
        for band in self.policy["approval_bands_egp"]:
            if band["max"] is None or total_egp <= band["max"]:
                return band["role"]
        return self.policy["approval_bands_egp"][-1]["role"]
