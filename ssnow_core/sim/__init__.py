"""Deferred physics simulation scenarios (Phase 2)."""

from .base import Scenario, ScenarioMeta, SIMULATIONS, get_scenario, list_scenarios, register

# Import scenario modules so they register on import.
from . import flare, impact  # noqa: F401

__all__ = ["Scenario", "ScenarioMeta", "SIMULATIONS", "get_scenario", "list_scenarios", "register"]
