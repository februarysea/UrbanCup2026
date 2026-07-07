"""Custom AgentSociety2 environment for NYC rain mobility decisions."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from agentsociety2.env import EnvBase, tool
from pydantic import BaseModel, Field


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve_project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


class MobilityContext(BaseModel):
    agent_id: int
    hour: str
    zone_id: str
    rain_phase: str
    precipitation: float
    bike_trip_count: int
    taxi_pickup_count: int
    subway_ridership: int
    scenario: str


class DecisionRecord(BaseModel):
    agent_id: int
    hour: str
    decision: str = Field(..., description="travel_now, delay, or cancel")
    mode: str = Field(..., description="bike, taxi, subway, none")
    reason: str


class RainMobilityEnv(EnvBase):
    """Rainstorm mobility context and decision logging environment."""

    def __init__(
        self,
        panel_path: str = "",
        events_path: str = "",
        agent_population_path: str = "",
        scenario: str = "baseline",
        decision_log_path: str = "",
    ):
        super().__init__()
        self.panel_path = panel_path
        self.events_path = events_path
        self.agent_population_path = agent_population_path
        self.scenario = scenario
        self.decision_log_path = decision_log_path
        self._panel: pd.DataFrame = pd.DataFrame()
        self._agents: dict[int, dict[str, Any]] = {}
        self._hours: list[pd.Timestamp] = []
        self._hour_index = 0
        self._decisions: list[dict[str, Any]] = []

    @classmethod
    def description(cls) -> str:
        return "NYC rainstorm mobility environment for bike, taxi, and subway mode-choice decisions."

    @classmethod
    def init_description(cls) -> str:
        return """RainMobilityEnv initialization.

Parameters:
- panel_path (str): CSV with zone-hour mobility/weather context.
- events_path (str): JSON rainstorm event metadata.
- agent_population_path (str): JSON synthesized traveler archetypes.
- scenario (str): baseline, early_warning, transit_guidance, or taxi_support.
- decision_log_path (str): JSONL path for agent decisions.

Agents should call observe_mobility_context(agent_id) and then record_travel_decision(...).
"""

    async def init(self, start_datetime: datetime):
        await super().init(start_datetime)
        if self.panel_path:
            self._panel = pd.read_csv(_resolve_project_path(self.panel_path), parse_dates=["hour"])
            self._panel["zone_id"] = self._panel["zone_id"].astype(str)
            self._hours = sorted(self._panel["hour"].dropna().unique())
        if self.agent_population_path:
            data = json.loads(_resolve_project_path(self.agent_population_path).read_text(encoding="utf-8"))
            self._agents = {int(agent["id"]): agent for agent in data.get("agents", [])}
        if self.decision_log_path:
            decision_log = _resolve_project_path(self.decision_log_path)
            decision_log.parent.mkdir(parents=True, exist_ok=True)
            decision_log.write_text("", encoding="utf-8")

    async def step(self, tick: int, t: datetime):
        self.t = t
        if self._hours:
            self._hour_index = min(self._hour_index + 1, len(self._hours) - 1)

    def _current_hour(self) -> pd.Timestamp | None:
        if not self._hours:
            return None
        return self._hours[min(self._hour_index, len(self._hours) - 1)]

    def _context_for_agent(self, agent_id: int) -> dict[str, Any]:
        hour = self._current_hour()
        agent = self._agents.get(int(agent_id), {})
        zone_id = str(agent.get("home_zone", "unknown"))
        if hour is None or self._panel.empty:
            return {
                "agent_id": int(agent_id),
                "hour": self.t.isoformat(),
                "zone_id": zone_id,
                "rain_phase": "unknown",
                "precipitation": 0.0,
                "bike_trip_count": 0,
                "taxi_pickup_count": 0,
                "subway_ridership": 0,
                "scenario": self.scenario,
            }
        subset = self._panel[(self._panel["hour"] == hour) & (self._panel["zone_id"] == zone_id)]
        if subset.empty:
            subset = self._panel[self._panel["hour"] == hour]
        row = subset.iloc[0].to_dict()
        return {
            "agent_id": int(agent_id),
            "hour": pd.Timestamp(hour).isoformat(),
            "zone_id": zone_id,
            "rain_phase": str(row.get("rain_phase", "control")),
            "precipitation": float(row.get("precipitation", 0.0)),
            "bike_trip_count": int(row.get("bike_trip_count", 0)),
            "taxi_pickup_count": int(row.get("taxi_pickup_count", 0)),
            "subway_ridership": int(row.get("subway_ridership", 0)),
            "scenario": self.scenario,
        }

    @tool(readonly=True, kind="observe")
    async def observe_mobility_context(self, agent_id: int) -> dict[str, Any]:
        """Observe current rain, bike, taxi, and subway context for this traveler's home zone."""
        return MobilityContext(**self._context_for_agent(agent_id)).model_dump()

    @tool(readonly=True)
    async def get_traveler_profile(self, agent_id: int) -> dict[str, Any]:
        """Return the synthesized mobility archetype profile for a traveler."""
        return self._agents.get(int(agent_id), {})

    @tool(readonly=False)
    async def record_travel_decision(
        self,
        agent_id: int,
        decision: str,
        mode: str,
        reason: str,
    ) -> dict[str, Any]:
        """Record the traveler's mode decision for the current simulation hour."""
        context = self._context_for_agent(agent_id)
        record = DecisionRecord(
            agent_id=int(agent_id),
            hour=context["hour"],
            decision=str(decision),
            mode=str(mode),
            reason=str(reason),
        ).model_dump()
        record.update(
            {
                "scenario": self.scenario,
                "rain_phase": context["rain_phase"],
                "zone_id": context["zone_id"],
                "precipitation": context["precipitation"],
            }
        )
        self._decisions.append(record)
        if self.decision_log_path:
            with _resolve_project_path(self.decision_log_path).open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {"ok": True, "record": record}
