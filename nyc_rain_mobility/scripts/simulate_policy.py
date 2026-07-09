#!/usr/bin/env python3
"""Fast deterministic policy simulator for NYC rain mobility scenarios."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import pandas as pd

from common import PROJECT_DIR, PROCESSED_DIR, read_pipeline_config


def _scenario_adjustments(scenario: str, agent: dict) -> dict[str, float]:
    adjustment = {
        "bike_penalty": 0.0,
        "subway_bonus": 0.0,
        "bus_bonus": 0.0,
        "taxi_bonus": 0.0,
        "walk_penalty": 0.0,
        "delay_bonus": 0.0,
        "cancel_bonus": 0.0,
    }
    receptiveness = float(agent.get("policy_receptiveness", 0.6))
    if scenario == "early_warning":
        adjustment["bike_penalty"] += 0.15 * receptiveness
        adjustment["delay_bonus"] += 0.10 * receptiveness
    elif scenario == "transit_guidance":
        adjustment["bike_penalty"] += 0.12 * receptiveness
        adjustment["subway_bonus"] += 0.25 * receptiveness
        adjustment["bus_bonus"] += 0.18 * receptiveness
    elif scenario == "taxi_support":
        adjustment["taxi_bonus"] += 0.28 * receptiveness
        if agent["archetype"] == "low_alternative_access_user":
            adjustment["cancel_bonus"] -= 0.18 * receptiveness
            adjustment["taxi_bonus"] += 0.18 * receptiveness
    return adjustment


def _choose_mode(rng: random.Random, scores: dict[str, float]) -> str:
    cleaned = {k: max(0.0, v) for k, v in scores.items()}
    total = sum(cleaned.values())
    if total <= 0:
        return "cancel"
    pick = rng.random() * total
    accum = 0.0
    for mode, score in cleaned.items():
        accum += score
        if pick <= accum:
            return mode
    return next(reversed(cleaned))


def _stable_seed_offset(value: str) -> int:
    return sum((idx + 1) * ord(ch) for idx, ch in enumerate(value))


def simulate_scenario(
    scenario_name: str,
    scenario_policy: str,
    agents: list[dict],
    panel: pd.DataFrame,
    output: Path,
    seed: int,
    max_hours: int | None = None,
) -> pd.DataFrame:
    rng = random.Random(seed + _stable_seed_offset(scenario_name))
    hours = sorted(panel["hour"].dropna().unique())
    if max_hours is not None:
        hours = hours[:max_hours]
    zone_context = {
        (str(row.zone_id), row.hour): row
        for row in panel.itertuples(index=False)
    }
    fallback_by_hour = {
        row.hour: row
        for row in (
            panel.groupby("hour", as_index=False)
            .agg(
                precipitation=("precipitation", "max"),
                taxi_pickup_count=("taxi_pickup_count", "sum"),
                subway_ridership=("subway_ridership", "sum"),
                bike_trip_count=("bike_trip_count", "sum"),
                rain_phase=("rain_phase", "first"),
                event_id=("event_id", "first"),
            )
            .itertuples(index=False)
        )
    }
    rows = []
    for hour in hours:
        for agent in agents:
            zone_id = str(agent["home_zone"])
            ctx = zone_context.get((zone_id, hour), fallback_by_hour[hour])
            precipitation = float(getattr(ctx, "precipitation", 0.0))
            rain_phase = str(getattr(ctx, "rain_phase", "control"))
            rain_intensity = min(1.0, precipitation / 10.0)
            rain_sensitivity = float(agent["rain_sensitivity"])
            subway_access = float(agent["subway_accessibility"])
            bus_access = float(agent.get("bus_accessibility", 0.0))
            taxi_avail = float(agent["taxi_availability"])
            cost_sensitivity = float(agent["cost_sensitivity"])
            flexibility = float(agent["schedule_flexibility"])
            walk_tolerance = float(agent.get("walk_tolerance", 0.2))
            adj = _scenario_adjustments(scenario_policy, agent)

            bike_score = 0.55 if agent["preferred_mode"] == "bike" else 0.20
            bike_score -= rain_intensity * rain_sensitivity
            bike_score -= adj["bike_penalty"] * rain_intensity

            subway_score = 0.18 + subway_access * 0.42
            subway_score += adj["subway_bonus"] * rain_intensity
            if agent["preferred_mode"] == "subway":
                subway_score += 0.20

            bus_score = 0.12 + bus_access * 0.38
            bus_score += adj["bus_bonus"] * rain_intensity
            bus_score -= rain_intensity * 0.04
            if agent["preferred_mode"] == "bus":
                bus_score += 0.22

            taxi_score = 0.15 + taxi_avail * 0.35
            taxi_score -= cost_sensitivity * 0.12
            taxi_score += rain_intensity * 0.12
            taxi_score += adj["taxi_bonus"] * rain_intensity
            if agent["preferred_mode"] == "taxi":
                taxi_score += 0.18

            walk_score = 0.08 + walk_tolerance * 0.25
            walk_score -= rain_intensity * (0.10 + rain_sensitivity * 0.35)
            walk_score -= adj["walk_penalty"] * rain_intensity
            if agent["preferred_mode"] == "walk":
                walk_score += 0.25

            delay_score = flexibility * (0.15 + rain_intensity * 0.45)
            delay_score += adj["delay_bonus"] * rain_intensity
            cancel_score = max(0.02, flexibility * 0.08 + rain_intensity * 0.18)
            cancel_score += adj["cancel_bonus"] * rain_intensity
            if agent["trip_purpose"] in {"commute", "necessary_trip"}:
                cancel_score *= 0.55
                delay_score *= 0.85

            decision = _choose_mode(
                rng,
                {
                    "bike": bike_score,
                    "subway": subway_score,
                    "bus": bus_score,
                    "taxi": taxi_score,
                    "walk": walk_score,
                    "delay": delay_score,
                    "cancel": cancel_score,
                },
            )
            heat_or_rain_exposure = 1.0 if decision in {"bike", "walk"} and precipitation > 0 else 0.0
            unmet = 1 if decision in {"delay", "cancel"} else 0
            rows.append(
                {
                    "scenario": scenario_name,
                    "policy": scenario_policy,
                    "agent_id": agent["id"],
                    "archetype": agent["archetype"],
                    "home_zone": zone_id,
                    "origin_zone": str(agent.get("origin_zone", agent.get("home_zone", zone_id))),
                    "destination_zone": str(agent.get("destination_zone", agent.get("work_zone", ""))),
                    "hour": pd.Timestamp(hour).isoformat(),
                    "rain_phase": rain_phase,
                    "event_id": str(getattr(ctx, "event_id", "")),
                    "precipitation": precipitation,
                    "decision": decision,
                    "chosen_mode": decision if decision not in {"delay", "cancel"} else "none",
                    "rain_exposure": heat_or_rain_exposure,
                    "unmet_demand": unmet,
                }
            )
    decisions = pd.DataFrame(rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    decisions.to_csv(output, index=False)
    return decisions


def simulate_all(agents_path: Path, panel_path: Path, max_hours: int | None = None) -> list[Path]:
    cfg = read_pipeline_config()
    seed = int(cfg["simulation"]["seed"])
    agents = json.loads(agents_path.read_text(encoding="utf-8"))["agents"]
    panel = pd.read_csv(panel_path, parse_dates=["hour"])
    written = []
    for experiment_name, scenario in cfg["scenarios"].items():
        run_dir = PROJECT_DIR / "hypothesis_1" / experiment_name / "run"
        output = run_dir / "simulated_decisions.csv"
        simulate_scenario(
            experiment_name,
            scenario["policy"],
            agents,
            panel,
            output,
            seed,
            max_hours=max_hours,
        )
        written.append(output)
    return written


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agents", type=Path, default=PROJECT_DIR / "config" / "agent_population.json")
    parser.add_argument("--panel", type=Path, default=PROCESSED_DIR / "panel_labeled.csv")
    parser.add_argument("--max-hours", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    written = simulate_all(args.agents, args.panel, args.max_hours)
    print("Wrote simulated decisions:")
    for path in written:
        print(f"  {path}")


if __name__ == "__main__":
    main()
