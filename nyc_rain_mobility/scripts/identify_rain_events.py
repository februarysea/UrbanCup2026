#!/usr/bin/env python3
"""Identify rainstorm event windows and label panel rows."""

from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path

import pandas as pd

from common import PROCESSED_DIR, read_pipeline_config, write_json


def _segments(hours: list[pd.Timestamp]) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    if not hours:
        return []
    segments = []
    start = prev = hours[0]
    for hour in hours[1:]:
        if hour - prev == pd.Timedelta(hours=1):
            prev = hour
            continue
        segments.append((start, prev))
        start = prev = hour
    segments.append((start, prev))
    return segments


def label_events(panel_path: Path, output_panel: Path, output_events: Path) -> tuple[pd.DataFrame, list[dict]]:
    cfg = read_pipeline_config()["rainstorm"]
    threshold = float(cfg["rain_threshold_mm_per_hour"])
    min_len = int(cfg["min_consecutive_rain_hours"])
    pre_hours = int(cfg["pre_window_hours"])
    post_hours = int(cfg["post_window_hours"])
    control_max = float(cfg["control_max_precipitation_mm_per_hour"])

    panel = pd.read_csv(panel_path, parse_dates=["hour"])
    weather = panel[["hour", "precipitation"]].drop_duplicates().sort_values("hour")
    rain_hours = weather.loc[weather["precipitation"] >= threshold, "hour"].tolist()
    raw_segments = _segments(rain_hours)
    segments = [
        (start, end)
        for start, end in raw_segments
        if int((end - start) / pd.Timedelta(hours=1)) + 1 >= min_len
    ]

    panel["event_id"] = ""
    panel["rain_phase"] = "control"
    panel.loc[panel["precipitation"] > control_max, "rain_phase"] = "other_rain"

    events = []
    for idx, (start, end) in enumerate(segments, start=1):
        event_id = f"rain_{idx:02d}"
        pre_start = start - timedelta(hours=pre_hours)
        post_end = end + timedelta(hours=post_hours)
        during_mask = panel["hour"].between(start, end)
        pre_mask = panel["hour"].between(pre_start, start - timedelta(hours=1))
        post_mask = panel["hour"].between(end + timedelta(hours=1), post_end)
        panel.loc[pre_mask, ["event_id", "rain_phase"]] = [event_id, "pre_rain"]
        panel.loc[during_mask, ["event_id", "rain_phase"]] = [event_id, "during_rain"]
        panel.loc[post_mask, ["event_id", "rain_phase"]] = [event_id, "post_rain"]
        events.append(
            {
                "event_id": event_id,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "max_precipitation": float(
                    weather.loc[weather["hour"].between(start, end), "precipitation"].max()
                ),
                "pre_window_hours": pre_hours,
                "post_window_hours": post_hours,
            }
        )

    output_panel.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(output_panel, index=False)
    write_json(output_events, events)
    return panel, events


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=PROCESSED_DIR / "panel_zone_hour.csv")
    parser.add_argument("--output-panel", type=Path, default=PROCESSED_DIR / "panel_labeled.csv")
    parser.add_argument("--output-events", type=Path, default=PROCESSED_DIR / "rain_events.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    panel, events = label_events(args.panel, args.output_panel, args.output_events)
    print(
        f"Wrote {args.output_panel} rows={len(panel)} events={len(events)} "
        f"phases={panel['rain_phase'].value_counts().to_dict()}"
    )


if __name__ == "__main__":
    main()

