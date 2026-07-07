#!/usr/bin/env python3
"""Generate station-to-taxi-zone mapping files from station coordinates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd
from shapely.geometry import Point, shape
from shapely.prepared import prep

from common import (
    CONFIG_DIR,
    RAW_DIR,
    SAMPLE_DIR,
    iter_csv_dicts,
    normalize_zone_id,
    read_many,
    require_paths,
    resolve_manifest_paths,
)


def _load_zones(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    zones = []
    for feature in payload.get("features", []):
        props = feature.get("properties", {})
        location_id = props.get("locationid") or props.get("LocationID") or props.get("location_id")
        if location_id is None:
            continue
        geom = shape(feature["geometry"])
        zones.append(
            {
                "zone_id": str(int(float(location_id))),
                "zone_name": props.get("zone", ""),
                "borough": props.get("borough", ""),
                "geometry": geom,
                "prepared": prep(geom),
            }
        )
    if not zones:
        raise ValueError(f"No taxi zones loaded from {path}")
    return zones


def _point_zone(lon: float, lat: float, zones: list[dict[str, Any]]) -> str:
    point = Point(float(lon), float(lat))
    for zone in zones:
        if zone["prepared"].contains(point) or zone["geometry"].touches(point):
            return zone["zone_id"]
    return "unknown"


def _collect_bike_stations(sample: bool, max_rows: int | None) -> pd.DataFrame:
    paths = require_paths("citibike", sample=sample)
    stations: dict[str, dict[str, Any]] = {}
    seen = 0
    for path in paths:
        for row in iter_csv_dicts(path):
            seen += 1
            for prefix in ["start", "end"]:
                station_id = row.get(f"{prefix}_station_id")
                lat = row.get(f"{prefix}_lat")
                lng = row.get(f"{prefix}_lng")
                if station_id and lat and lng:
                    stations[str(station_id)] = {
                        "station_id": str(station_id),
                        "latitude": float(lat),
                        "longitude": float(lng),
                    }
            if max_rows and seen >= max_rows:
                break
        if max_rows and seen >= max_rows:
            break
    return pd.DataFrame(stations.values())


def _collect_mta_stations(sample: bool) -> pd.DataFrame:
    paths = require_paths("mta", sample=sample)
    frames = []
    for path in paths:
        frame = pd.read_csv(path)
        if {"station_complex_id", "latitude", "longitude"}.issubset(frame.columns):
            frames.append(frame[["station_complex_id", "latitude", "longitude"]])
    if not frames:
        raise ValueError("MTA files do not include station_complex_id, latitude, longitude.")
    stations = pd.concat(frames, ignore_index=True).dropna().drop_duplicates("station_complex_id")
    stations["station_complex_id"] = stations["station_complex_id"].astype(str)
    return stations


def generate_maps(
    *,
    sample: bool,
    zone_geojson: Path | None,
    output_bike: Path,
    output_mta: Path,
    max_bike_rows: int | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if zone_geojson is None:
        zone_paths = resolve_manifest_paths("taxi_zones_geojson", sample=sample)
        if not zone_paths:
            default = SAMPLE_DIR / "taxi_zones.geojson" if sample else RAW_DIR / "taxi_zones.geojson"
            raise FileNotFoundError(f"Taxi zone GeoJSON not found: {default}")
        zone_geojson = zone_paths[0]
    zones = _load_zones(zone_geojson)

    bike = _collect_bike_stations(sample=sample, max_rows=max_bike_rows)
    bike["zone_id"] = [
        _point_zone(lon, lat, zones)
        for lon, lat in zip(bike["longitude"], bike["latitude"])
    ]
    bike_out = bike[["station_id", "zone_id"]].sort_values("station_id")
    bike_out["zone_id"] = normalize_zone_id(bike_out["zone_id"])
    output_bike.parent.mkdir(parents=True, exist_ok=True)
    bike_out.to_csv(output_bike, index=False)

    mta = _collect_mta_stations(sample=sample)
    mta["zone_id"] = [
        _point_zone(lon, lat, zones)
        for lon, lat in zip(mta["longitude"], mta["latitude"])
    ]
    mta_out = mta[["station_complex_id", "zone_id"]].sort_values("station_complex_id")
    mta_out["zone_id"] = normalize_zone_id(mta_out["zone_id"])
    output_mta.parent.mkdir(parents=True, exist_ok=True)
    mta_out.to_csv(output_mta, index=False)

    return bike_out, mta_out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="store_true", help="Use bundled sample inputs.")
    parser.add_argument("--zone-geojson", type=Path, default=None)
    parser.add_argument("--output-bike", type=Path, default=CONFIG_DIR / "station_zone_map_bike.csv")
    parser.add_argument("--output-mta", type=Path, default=CONFIG_DIR / "station_zone_map_mta.csv")
    parser.add_argument(
        "--max-bike-rows",
        type=int,
        default=500000,
        help="Max Citi Bike rows to scan for station coordinates; use 0 for no limit.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    max_rows = None if args.max_bike_rows == 0 else args.max_bike_rows
    bike, mta = generate_maps(
        sample=args.sample,
        zone_geojson=args.zone_geojson,
        output_bike=args.output_bike,
        output_mta=args.output_mta,
        max_bike_rows=max_rows,
    )
    print(f"Wrote {args.output_bike} rows={len(bike)} unknown={(bike['zone_id'] == 'unknown').sum()}")
    print(f"Wrote {args.output_mta} rows={len(mta)} unknown={(mta['zone_id'] == 'unknown').sum()}")


if __name__ == "__main__":
    main()

