#!/usr/bin/env python3
"""Compute empirical rainstorm mobility shifts."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from common import PROCESSED_DIR, TABLES_DIR, write_json


MODE_COLUMNS = {
    "bike": "bike_trip_count",
    "taxi": "taxi_pickup_count",
    "subway": "subway_ridership",
    "bus": "bus_ridership",
}


def _safe_ratio(value: float, baseline: float) -> float:
    if baseline == 0:
        return 0.0 if value == 0 else float("inf")
    return value / baseline


def analyze(panel_path: Path, output_dir: Path) -> dict:
    panel = pd.read_csv(panel_path, parse_dates=["hour"])
    output_dir.mkdir(parents=True, exist_ok=True)
    mode_columns = {mode: col for mode, col in MODE_COLUMNS.items() if col in panel.columns}

    phase_aggs = {
        "zone_hour_count": ("zone_id", "count"),
        "mean_precipitation": ("precipitation", "mean"),
    }
    for col in ["bike_trip_count", "bike_member_count", "bike_casual_count", "taxi_pickup_count", "subway_ridership", "bus_ridership"]:
        if col in panel.columns:
            phase_aggs[col] = (col, "sum")
    phase_summary = (
        panel.groupby("rain_phase", as_index=False)
        .agg(**phase_aggs)
        .sort_values("rain_phase")
    )
    phase_summary.to_csv(output_dir / "phase_summary.csv", index=False)

    control = panel[panel["rain_phase"] == "control"]
    during = panel[panel["rain_phase"] == "during_rain"]
    comparisons = {}
    for mode, col in mode_columns.items():
        control_mean = float(control[col].mean()) if not control.empty else 0.0
        during_mean = float(during[col].mean()) if not during.empty else 0.0
        comparisons[mode] = {
            "control_mean_per_zone_hour": control_mean,
            "during_rain_mean_per_zone_hour": during_mean,
            "during_to_control_ratio": _safe_ratio(during_mean, control_mean),
            "percent_change": (_safe_ratio(during_mean, control_mean) - 1.0) * 100.0
            if control_mean
            else 0.0,
        }

    zone_aggs = {"mean_precipitation": ("precipitation", "mean")}
    for col in mode_columns.values():
        zone_aggs[col] = (col, "sum")
    zone_phase = (
        panel.groupby(["zone_id", "rain_phase"], as_index=False)
        .agg(**zone_aggs)
    )
    zone_phase.to_csv(output_dir / "zone_phase_summary.csv", index=False)

    zone_control = zone_phase[zone_phase["rain_phase"] == "control"].set_index("zone_id")
    zone_during = zone_phase[zone_phase["rain_phase"] == "during_rain"].set_index("zone_id")
    zone_rows = []
    for zone_id in sorted(set(zone_control.index) | set(zone_during.index)):
        row = {"zone_id": zone_id}
        for mode, col in mode_columns.items():
            c = float(zone_control[col].get(zone_id, 0.0)) if col in zone_control else 0.0
            d = float(zone_during[col].get(zone_id, 0.0)) if col in zone_during else 0.0
            row[f"{mode}_during_to_control_ratio"] = _safe_ratio(d, c)
            row[f"{mode}_absolute_change"] = d - c
        zone_rows.append(row)
    zone_impacts = pd.DataFrame(zone_rows)
    zone_impacts.to_csv(output_dir / "zone_impacts.csv", index=False)

    summary = {
        "input_panel": str(panel_path),
        "phase_counts": panel["rain_phase"].value_counts().to_dict(),
        "mode_comparisons": comparisons,
        "events_present": sorted([e for e in panel["event_id"].dropna().unique() if e]),
        "outputs": {
            "phase_summary": str(output_dir / "phase_summary.csv"),
            "zone_phase_summary": str(output_dir / "zone_phase_summary.csv"),
            "zone_impacts": str(output_dir / "zone_impacts.csv"),
        },
    }
    write_json(output_dir / "empirical_summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=PROCESSED_DIR / "panel_labeled.csv")
    parser.add_argument("--output-dir", type=Path, default=TABLES_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = analyze(args.panel, args.output_dir)
    print(f"Wrote empirical summary to {args.output_dir / 'empirical_summary.json'}")
    print(summary["mode_comparisons"])


if __name__ == "__main__":
    main()
