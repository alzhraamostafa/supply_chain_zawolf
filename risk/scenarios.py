"""Planted scenarios: a hidden supplier behaviour generates a delivery history AND the next outcome.
The engine only sees the history and the stock cover, never the hidden numbers."""
import random

from .engine import Delivery, SupplyHistory


def make_scenario(rng: random.Random):
    lead = rng.choice([4, 6, 8, 10, 12])
    p_late = rng.choice([0.03, 0.08, 0.15, 0.30, 0.50])
    n_suppliers = rng.choice([1, 1, 2, 3])
    max_delay = max(1, lead // 2)
    deliveries = []
    for _ in range(rng.choice([12, 20, 26])):
        late = rng.random() < p_late
        actual = lead + (rng.randint(1, max_delay) if late else 0)
        deliveries.append(Delivery(lead, actual, rng.uniform(0.985, 0.998)))
    cover = rng.uniform(0.5 * lead, 2.5 * lead)
    history = SupplyHistory("material", deliveries, n_suppliers, criticality=rng.choice([0.1, 0.3, 0.9]),
                            cover_days=cover)
    next_delay = rng.randint(1, max_delay) if rng.random() < p_late else 0
    shortage = cover < lead + next_delay        # stock runs out before the order arrives
    return history, shortage