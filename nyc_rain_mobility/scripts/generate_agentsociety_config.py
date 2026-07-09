#!/usr/bin/env python3
"""Generate AgentSociety2 init_config.json and steps.yaml for policy scenarios."""

from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path

import pandas as pd
import yaml

from common import PROJECT_DIR, PROCESSED_DIR, read_pipeline_config, write_json


EXPERIMENT_DIR = PROJECT_DIR / "hypothesis_1"


def _project_relative(path: Path) -> str:
    return str(path.resolve().relative_to(PROJECT_DIR.resolve()))


def _profile_text(agent: dict, scenario: str) -> str:
    return (
        f"You are {agent['name']}, a New York City traveler. "
        f"Archetype: {agent['archetype']}. Home taxi zone: {agent['home_zone']}. "
        f"Destination taxi zone: {agent['destination_zone']}. Trip purpose: {agent['trip_purpose']}. "
        f"Income group: {agent.get('income_group', 'unknown')}. "
        f"Preferred mode: {agent['preferred_mode']}. "
        f"Rain sensitivity: {agent['rain_sensitivity']}. Subway accessibility: {agent['subway_accessibility']}. "
        f"Bus accessibility: {agent.get('bus_accessibility', 0.0)}. Taxi availability: {agent['taxi_availability']}. "
        f"Cost sensitivity: {agent['cost_sensitivity']}. Schedule flexibility: {agent['schedule_flexibility']}. "
        f"Alternative access: {agent.get('alternative_access', 0.0)}. "
        f"Policy scenario: {scenario}. At each step, observe the rain mobility context and choose "
        "travel_now, delay, or cancel; if traveling, choose bike, subway, bus, taxi, or walk."
    )


def _start_time(panel_path: Path) -> str:
    panel = pd.read_csv(panel_path, parse_dates=["hour"])
    if panel.empty:
        return "2024-07-01T00:00:00"
    return panel["hour"].min().isoformat()


def generate_configs(
    agents_path: Path,
    panel_path: Path,
    events_path: Path,
    max_hours: int | None,
) -> list[Path]:
    cfg = read_pipeline_config()
    simulation_cfg = cfg["simulation"]
    scenario_cfg = cfg["scenarios"]
    agents = json.loads(agents_path.read_text(encoding="utf-8"))["agents"]
    tick = int(simulation_cfg["tick_seconds"])
    hours = int(max_hours or simulation_cfg["max_hours"])
    start_t = _start_time(panel_path)

    written = []
    for experiment_name, scenario in scenario_cfg.items():
        init_dir = EXPERIMENT_DIR / experiment_name / "init"
        run_dir = EXPERIMENT_DIR / experiment_name / "run"
        init_dir.mkdir(parents=True, exist_ok=True)
        run_dir.mkdir(parents=True, exist_ok=True)
        policy = scenario["policy"]
        env_kwargs = {
            "panel_path": _project_relative(panel_path),
            "events_path": _project_relative(events_path),
            "agent_population_path": _project_relative(agents_path),
            "scenario": policy,
            "decision_log_path": _project_relative(run_dir / "agent_decisions.jsonl"),
        }
        agent_configs = []
        for agent in agents:
            kwargs = {
                "id": int(agent["id"]),
                "name": agent["name"],
                "profile": _profile_text(agent, policy),
                "archetype": agent["archetype"],
                "home_zone": agent["home_zone"],
                "origin_zone": agent.get("origin_zone", agent["home_zone"]),
                "work_zone": agent.get("work_zone", agent["destination_zone"]),
                "destination_zone": agent["destination_zone"],
                "trip_purpose": agent["trip_purpose"],
                "preferred_mode": agent["preferred_mode"],
                "max_react_turns": 5,
                "enable_memory": False,
            }
            agent_configs.append(
                {
                    "agent_id": int(agent["id"]),
                    "agent_type": "PersonAgent",
                    "kwargs": kwargs,
                }
            )

        init_config = {
            "env_modules": [
                {
                    "module_type": "RainMobilityEnv",
                    "kwargs": env_kwargs,
                }
            ],
            "agents": agent_configs,
            "codegen_router": {"final_summary_enabled": True},
        }
        steps = {
            "start_t": start_t,
            "steps": [
                {
                    "type": "run",
                    "num_steps": hours,
                    "tick": tick,
                }
            ],
        }
        init_path = init_dir / "init_config.json"
        steps_path = init_dir / "steps.yaml"
        write_json(init_path, init_config)
        steps_path.write_text(
            yaml.safe_dump(steps, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        written.extend([init_path, steps_path])
    return written


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agents", type=Path, default=PROJECT_DIR / "config" / "agent_population.json")
    parser.add_argument("--panel", type=Path, default=PROCESSED_DIR / "panel_labeled.csv")
    parser.add_argument("--events", type=Path, default=PROCESSED_DIR / "rain_events.json")
    parser.add_argument("--max-hours", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    written = generate_configs(args.agents, args.panel, args.events, args.max_hours)
    print("Generated AgentSociety2 configs:")
    for path in written:
        print(f"  {path}")


if __name__ == "__main__":
    main()
