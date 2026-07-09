#!/usr/bin/env python3
"""Evaluate deterministic and AgentSociety2 decision logs."""

from __future__ import annotations

import argparse
import glob
from pathlib import Path

import pandas as pd

from common import PROJECT_DIR, TABLES_DIR, write_json


def evaluate(decision_paths: list[Path], output_dir: Path) -> pd.DataFrame:
    frames = []
    for path in decision_paths:
        if path.exists():
            frame = pd.read_csv(path)
            if "scenario" not in frame.columns:
                frame["scenario"] = path.parents[1].name
            frames.append(frame)
    if not frames:
        raise FileNotFoundError("No decision files found for evaluation.")
    decisions = pd.concat(frames, ignore_index=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    decisions.to_csv(output_dir / "all_policy_decisions.csv", index=False)

    rows = []
    for scenario, group in decisions.groupby("scenario"):
        total = len(group)
        during = group[group["rain_phase"] == "during_rain"]
        row = {
            "scenario": scenario,
            "total_decisions": total,
            "during_rain_decisions": len(during),
            "bike_share": float((group["decision"] == "bike").mean()),
            "taxi_share": float((group["decision"] == "taxi").mean()),
            "subway_share": float((group["decision"] == "subway").mean()),
            "bus_share": float((group["decision"] == "bus").mean()),
            "walk_share": float((group["decision"] == "walk").mean()),
            "delay_share": float((group["decision"] == "delay").mean()),
            "cancel_share": float((group["decision"] == "cancel").mean()),
            "unmet_demand_share": float(group["unmet_demand"].mean()),
            "rain_exposure_share": float(group["rain_exposure"].mean()),
            "during_unmet_demand_share": float(during["unmet_demand"].mean()) if len(during) else 0.0,
            "during_rain_exposure_share": float(during["rain_exposure"].mean()) if len(during) else 0.0,
        }
        rows.append(row)
    metrics = pd.DataFrame(rows).sort_values("scenario")
    metrics.to_csv(output_dir / "policy_metrics.csv", index=False)

    fairness = (
        decisions.groupby(["scenario", "archetype"], as_index=False)
        .agg(
            decisions=("decision", "count"),
            unmet_demand_share=("unmet_demand", "mean"),
            rain_exposure_share=("rain_exposure", "mean"),
            cancel_share=("decision", lambda s: float((s == "cancel").mean())),
        )
        .sort_values(["scenario", "archetype"])
    )
    fairness.to_csv(output_dir / "policy_fairness_by_archetype.csv", index=False)
    write_json(
        output_dir / "policy_metrics_summary.json",
        {
            "decision_files": [str(p) for p in decision_paths],
            "metrics_file": str(output_dir / "policy_metrics.csv"),
            "fairness_file": str(output_dir / "policy_fairness_by_archetype.csv"),
        },
    )
    return metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--decision-glob",
        default=str(PROJECT_DIR / "hypothesis_1" / "experiment_*" / "run" / "simulated_decisions.csv"),
    )
    parser.add_argument("--output-dir", type=Path, default=TABLES_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = [Path(p) for p in sorted(glob.glob(args.decision_glob))]
    metrics = evaluate(paths, args.output_dir)
    print(f"Wrote policy metrics to {args.output_dir / 'policy_metrics.csv'}")
    print(metrics.to_string(index=False))


if __name__ == "__main__":
    main()
