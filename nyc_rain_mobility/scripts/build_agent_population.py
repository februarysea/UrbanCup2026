#!/usr/bin/env python3
"""Synthesize traveler archetypes for the AgentSociety2 rain mobility experiment."""

from __future__ import annotations

import argparse
import random
from pathlib import Path

import pandas as pd

from common import CONFIG_DIR, PROCESSED_DIR, normalize_zone_id, read_pipeline_config, read_table, resolve_manifest_paths, write_json


ARCHETYPE_WEIGHTS = {
    "bike_commuter": 0.30,
    "bike_leisure_user": 0.20,
    "taxi_substituter": 0.18,
    "subway_substituter": 0.22,
    "low_alternative_access_user": 0.10,
}


def _weighted_choice(rng: random.Random, values: list[str], weights: list[float]) -> str:
    total = sum(weights)
    if total <= 0:
        return rng.choice(values)
    pick = rng.random() * total
    accum = 0.0
    for value, weight in zip(values, weights):
        accum += weight
        if pick <= accum:
            return value
    return values[-1]


def _load_acs(sample: bool) -> pd.DataFrame:
    paths = resolve_manifest_paths("acs_zone_features", sample=sample)
    if not paths:
        return pd.DataFrame()
    acs = read_table(paths[0])
    acs["zone_id"] = normalize_zone_id(acs["zone_id"])
    return acs


def build_agents(panel_path: Path, output: Path, sample: bool, num_agents: int | None) -> list[dict]:
    cfg = read_pipeline_config()["simulation"]
    seed = int(cfg["seed"])
    count = int(num_agents or cfg["num_agents"])
    rng = random.Random(seed)
    panel = pd.read_csv(panel_path, parse_dates=["hour"])
    panel["zone_id"] = normalize_zone_id(panel["zone_id"])
    acs = _load_acs(sample)

    zone_stats = (
        panel.groupby("zone_id", as_index=False)
        .agg(
            bike_total=("bike_trip_count", "sum"),
            taxi_total=("taxi_pickup_count", "sum"),
            subway_total=("subway_ridership", "sum"),
            rain_hours=("precipitation", lambda s: int((s > 0).sum())),
        )
    )
    if not acs.empty:
        zone_stats = zone_stats.merge(acs, on="zone_id", how="left")

    for col in [
        "median_household_income",
        "no_vehicle_share",
        "transit_commute_share",
        "low_income_share",
    ]:
        if col not in zone_stats.columns:
            zone_stats[col] = 0.0
        zone_stats[col] = zone_stats[col].fillna(zone_stats[col].median() if len(zone_stats) else 0.0)

    zone_stats["mobility_weight"] = (
        zone_stats["bike_total"]
        + zone_stats["taxi_total"]
        + zone_stats["subway_total"].clip(lower=1) / 100.0
    ).clip(lower=1.0)
    zones = zone_stats["zone_id"].astype(str).tolist()
    weights = zone_stats["mobility_weight"].astype(float).tolist()
    zone_lookup = zone_stats.set_index("zone_id").to_dict(orient="index")

    archetypes = list(ARCHETYPE_WEIGHTS)
    archetype_weights = list(ARCHETYPE_WEIGHTS.values())
    agents = []
    for idx in range(1, count + 1):
        archetype = _weighted_choice(rng, archetypes, archetype_weights)
        home_zone = _weighted_choice(rng, zones, weights)
        destination_zone = _weighted_choice(rng, zones, weights)
        z = zone_lookup[home_zone]
        subway_access = min(1.0, float(z["subway_total"]) / max(float(zone_stats["subway_total"].max()), 1.0))
        taxi_availability = min(1.0, float(z["taxi_total"]) / max(float(zone_stats["taxi_total"].max()), 1.0))
        low_income_share = float(z.get("low_income_share", 0.0) or 0.0)
        no_vehicle_share = float(z.get("no_vehicle_share", 0.0) or 0.0)

        if archetype == "bike_commuter":
            preferred_mode = "bike"
            trip_purpose = "commute"
            rain_sensitivity = rng.uniform(0.45, 0.70)
            schedule_flexibility = rng.uniform(0.10, 0.35)
            cost_sensitivity = rng.uniform(0.35, 0.60)
        elif archetype == "bike_leisure_user":
            preferred_mode = "bike"
            trip_purpose = "leisure"
            rain_sensitivity = rng.uniform(0.70, 0.95)
            schedule_flexibility = rng.uniform(0.55, 0.90)
            cost_sensitivity = rng.uniform(0.20, 0.55)
        elif archetype == "taxi_substituter":
            preferred_mode = "taxi"
            trip_purpose = "errand"
            rain_sensitivity = rng.uniform(0.40, 0.70)
            schedule_flexibility = rng.uniform(0.15, 0.45)
            cost_sensitivity = rng.uniform(0.15, 0.45)
        elif archetype == "subway_substituter":
            preferred_mode = "subway"
            trip_purpose = "commute"
            rain_sensitivity = rng.uniform(0.35, 0.65)
            schedule_flexibility = rng.uniform(0.15, 0.40)
            cost_sensitivity = rng.uniform(0.45, 0.75)
        else:
            preferred_mode = "bike"
            trip_purpose = "necessary_trip"
            rain_sensitivity = rng.uniform(0.55, 0.85)
            schedule_flexibility = rng.uniform(0.05, 0.25)
            cost_sensitivity = min(1.0, rng.uniform(0.55, 0.85) + low_income_share * 0.2)
            subway_access = min(subway_access, rng.uniform(0.05, 0.35))
            taxi_availability = min(taxi_availability, rng.uniform(0.05, 0.35))

        agents.append(
            {
                "id": idx,
                "name": f"Traveler-{idx:03d}",
                "archetype": archetype,
                "home_zone": home_zone,
                "destination_zone": destination_zone,
                "trip_purpose": trip_purpose,
                "preferred_mode": preferred_mode,
                "rain_sensitivity": round(rain_sensitivity, 3),
                "subway_accessibility": round(subway_access, 3),
                "taxi_availability": round(taxi_availability, 3),
                "cost_sensitivity": round(cost_sensitivity, 3),
                "schedule_flexibility": round(schedule_flexibility, 3),
                "no_vehicle_share": round(no_vehicle_share, 3),
                "policy_receptiveness": round(rng.uniform(0.45, 0.90), 3),
            }
        )

    write_json(output, {"seed": seed, "agents": agents})
    return agents


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="store_true", help="Use sample ACS zone features.")
    parser.add_argument("--panel", type=Path, default=PROCESSED_DIR / "panel_labeled.csv")
    parser.add_argument("--output", type=Path, default=CONFIG_DIR / "agent_population.json")
    parser.add_argument("--num-agents", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    agents = build_agents(args.panel, args.output, args.sample, args.num_agents)
    counts = pd.Series([a["archetype"] for a in agents]).value_counts().to_dict()
    print(f"Wrote {args.output} agents={len(agents)} archetypes={counts}")


if __name__ == "__main__":
    main()
