#!/usr/bin/env python3
"""Validate NYC rain mobility inputs and generated pipeline artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from common import (
    CONFIG_DIR,
    PRESENTATION_DIR,
    PROCESSED_DIR,
    PROJECT_DIR,
    TABLES_DIR,
    read_manifest,
    read_pipeline_config,
    resolve_manifest_paths,
    write_json,
)


@dataclass
class Check:
    name: str
    ok: bool
    message: str
    severity: str = "error"

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "severity": self.severity,
            "message": self.message,
        }


def _ok(name: str, message: str) -> Check:
    return Check(name=name, ok=True, message=message)


def _fail(name: str, message: str, severity: str = "error") -> Check:
    return Check(name=name, ok=False, message=message, severity=severity)


def _csv_header(path: Path) -> list[str]:
    suffixes = "".join(path.suffixes).lower()
    if suffixes.endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            names = [name for name in zf.namelist() if name.lower().endswith(".csv")]
            if not names:
                raise ValueError(f"No CSV files inside {path}")
            with zf.open(names[0]) as raw:
                first_line = raw.readline().decode("utf-8", errors="replace")
        return next(csv.reader([first_line]))
    if suffixes.endswith(".csv") or suffixes.endswith(".csv.gz"):
        frame = pd.read_csv(path, nrows=0)
        return list(frame.columns)
    if suffixes.endswith(".parquet"):
        try:
            import pyarrow.parquet as pq

            return list(pq.ParquetFile(path).schema.names)
        except Exception:
            return list(pd.read_parquet(path).columns)
    raise ValueError(f"Unsupported header format: {path}")


def _check_paths(key: str, *, sample: bool, required: bool = True) -> Check:
    paths = resolve_manifest_paths(key, sample=sample)
    if paths:
        return _ok(f"input:{key}:exists", f"{len(paths)} file(s) found")
    severity = "error" if required else "warning"
    return _fail(f"input:{key}:exists", "no files found", severity=severity)


def _check_columns(
    key: str,
    *,
    sample: bool,
    any_of: list[list[str]] | None = None,
    all_of: list[str] | None = None,
    required: bool = True,
) -> list[Check]:
    paths = resolve_manifest_paths(key, sample=sample)
    if not paths:
        severity = "error" if required else "warning"
        return [_fail(f"input:{key}:columns", "no file available for column check", severity)]
    checks = []
    try:
        columns = set(_csv_header(paths[0]))
    except Exception as exc:
        return [_fail(f"input:{key}:columns", f"failed to read header from {paths[0]}: {exc}")]
    if all_of:
        missing = [col for col in all_of if col not in columns]
        if missing:
            checks.append(_fail(f"input:{key}:required_columns", f"missing columns: {missing}"))
        else:
            checks.append(_ok(f"input:{key}:required_columns", f"all required columns present: {all_of}"))
    if any_of:
        for group in any_of:
            present = [col for col in group if col in columns]
            if present:
                checks.append(_ok(f"input:{key}:any_of:{'/'.join(group)}", f"present: {present}"))
            else:
                checks.append(_fail(f"input:{key}:any_of:{'/'.join(group)}", f"none present: {group}"))
    return checks


def validate_inputs(sample: bool) -> list[Check]:
    checks: list[Check] = []
    manifest = read_manifest()
    for key in manifest:
        required = key != "acs_zone_features"
        checks.append(_check_paths(key, sample=sample, required=required))

    checks.extend(
        _check_columns(
            "citibike",
            sample=sample,
            all_of=["started_at", "start_station_id", "start_lat", "start_lng", "member_casual"],
        )
    )
    checks.extend(
        _check_columns(
            "taxi",
            sample=sample,
            all_of=["PULocationID", "DOLocationID"],
            any_of=[["pickup_datetime", "tpep_pickup_datetime", "lpep_pickup_datetime"]],
        )
    )
    checks.extend(
        _check_columns(
            "mta",
            sample=sample,
            all_of=["transit_timestamp", "station_complex_id", "ridership"],
            any_of=[["latitude"], ["longitude"]],
        )
    )
    checks.extend(
        _check_columns(
            "weather",
            sample=sample,
            all_of=["time"],
            any_of=[["precipitation", "rain"]],
        )
    )
    checks.extend(
        _check_columns(
            "bike_station_zone_map",
            sample=sample,
            all_of=["station_id", "zone_id"],
        )
    )
    checks.extend(
        _check_columns(
            "mta_station_zone_map",
            sample=sample,
            all_of=["station_complex_id", "zone_id"],
        )
    )
    return checks


def _check_file(path: Path, name: str) -> Check:
    if path.exists():
        size = path.stat().st_size
        return _ok(name, f"exists size={size} bytes")
    return _fail(name, f"missing: {path}")


def _check_csv_nonempty(path: Path, name: str, required_cols: list[str]) -> list[Check]:
    if not path.exists():
        return [_fail(name, f"missing: {path}")]
    try:
        frame = pd.read_csv(path, nrows=1000)
    except Exception as exc:
        return [_fail(name, f"failed to read {path}: {exc}")]
    checks = [_ok(name, f"readable rows_checked={len(frame)}")]
    if frame.empty:
        checks.append(_fail(f"{name}:nonempty", "file has no rows"))
    missing = [col for col in required_cols if col not in frame.columns]
    if missing:
        checks.append(_fail(f"{name}:columns", f"missing columns: {missing}"))
    else:
        checks.append(_ok(f"{name}:columns", f"required columns present: {required_cols}"))
    return checks


def validate_outputs() -> list[Check]:
    checks: list[Check] = []
    checks.extend(
        _check_csv_nonempty(
            PROCESSED_DIR / "panel_labeled.csv",
            "output:panel_labeled",
            [
                "zone_id",
                "hour",
                "bike_trip_count",
                "taxi_pickup_count",
                "subway_ridership",
                "precipitation",
                "rain_phase",
            ],
        )
    )

    events_path = PROCESSED_DIR / "rain_events.json"
    checks.append(_check_file(events_path, "output:rain_events"))
    if events_path.exists():
        try:
            events = json.loads(events_path.read_text(encoding="utf-8"))
            if isinstance(events, list):
                checks.append(_ok("output:rain_events:json", f"{len(events)} event(s)"))
            else:
                checks.append(_fail("output:rain_events:json", "rain_events.json is not a list"))
        except Exception as exc:
            checks.append(_fail("output:rain_events:json", f"invalid JSON: {exc}"))

    agents_path = CONFIG_DIR / "agent_population.json"
    checks.append(_check_file(agents_path, "output:agent_population"))
    if agents_path.exists():
        try:
            data = json.loads(agents_path.read_text(encoding="utf-8"))
            agents = data.get("agents", [])
            if agents:
                checks.append(_ok("output:agent_population:agents", f"{len(agents)} agent(s)"))
            else:
                checks.append(_fail("output:agent_population:agents", "no agents found"))
        except Exception as exc:
            checks.append(_fail("output:agent_population:json", f"invalid JSON: {exc}"))

    scenario_names = list(read_pipeline_config().get("scenarios", {}))
    for scenario in scenario_names:
        base = PROJECT_DIR / "hypothesis_1" / scenario / "init"
        checks.append(_check_file(base / "init_config.json", f"output:{scenario}:init_config"))
        checks.append(_check_file(base / "steps.yaml", f"output:{scenario}:steps"))

    checks.extend(
        _check_csv_nonempty(
            TABLES_DIR / "policy_metrics.csv",
            "output:policy_metrics",
            ["scenario", "bike_share", "taxi_share", "subway_share", "unmet_demand_share"],
        )
    )
    checks.append(_check_file(PRESENTATION_DIR / "report.md", "output:report_md"))
    for chart in [
        "observed_mobility_by_phase.png",
        "policy_mode_shares.png",
        "unmet_demand_by_archetype.png",
    ]:
        checks.append(_check_file(PRESENTATION_DIR / "charts" / chart, f"output:chart:{chart}"))
    return checks


def write_summary(checks: list[Check], output: Path) -> None:
    summary = {
        "total": len(checks),
        "passed": sum(1 for check in checks if check.ok),
        "failed": sum(1 for check in checks if not check.ok),
        "errors": sum(1 for check in checks if not check.ok and check.severity == "error"),
        "warnings": sum(1 for check in checks if not check.ok and check.severity == "warning"),
        "checks": [check.as_dict() for check in checks],
    }
    write_json(output, summary)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="store_true", help="Validate bundled sample inputs instead of raw inputs.")
    parser.add_argument(
        "--check",
        choices=["all", "inputs", "outputs"],
        default="all",
        help="Validation scope.",
    )
    parser.add_argument("--output", type=Path, default=TABLES_DIR / "validation_summary.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    checks: list[Check] = []
    if args.check in {"all", "inputs"}:
        checks.extend(validate_inputs(sample=args.sample))
    if args.check in {"all", "outputs"}:
        checks.extend(validate_outputs())
    write_summary(checks, args.output)
    for check in checks:
        status = "OK" if check.ok else check.severity.upper()
        print(f"[{status}] {check.name}: {check.message}")
    errors = [check for check in checks if not check.ok and check.severity == "error"]
    if errors:
        raise SystemExit(1)
    print(f"Wrote validation summary to {args.output}")


if __name__ == "__main__":
    main()

