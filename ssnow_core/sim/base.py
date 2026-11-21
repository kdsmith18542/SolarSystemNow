"""Deterministic physics simulation scenarios (Phase 2).

All scenarios are labeled SIMULATION and never mixed with observed data.
Formulas are published approximations intended for order-of-magnitude
education, not forecasts. Each scenario cites its source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

SIMULATIONS: dict[str, type["Scenario"]] = {}


@dataclass(frozen=True)
class Param:
    id: str
    label: str
    type: str  # "number" | "select" | "boolean"
    unit: str | None = None
    default: Any = None
    min: float | None = None
    max: float | None = None
    options: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class ScenarioMeta:
    id: str
    title: str
    description: str
    citation: str
    params: list[Param]
    output_labels: dict[str, str]  # result key -> human label


class Scenario(Protocol):
    meta: ScenarioMeta

    def run(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Execute the simulation. Return a dict of result values."""
        ...


def register(sim_cls: type[Scenario]) -> type[Scenario]:
    SIMULATIONS[sim_cls.meta.id] = sim_cls
    return sim_cls


def list_scenarios() -> list[ScenarioMeta]:
    return [cls.meta for cls in SIMULATIONS.values()]


def get_scenario(sim_id: str) -> type[Scenario] | None:
    return SIMULATIONS.get(sim_id)
