#!/usr/bin/env python3
"""Build a taxi-zone by hour panel from mobility and weather data."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from common import (
    PROCESSED_DIR,
    ensure_dirs,
    first_existing_column,
    iter_csv_chunks,
    normalize_zone_id,
    parse_hour,
    read_many,
    read_table,
    require_paths,
    resolve_manifest_paths,
)


def aggregate_bike(sample: bool) -> pd.DataFrame:
    bike_paths = require_paths("citibike", sample=sample)
    station_map = read_table(require_paths("bike_station_zone_map", sample=sample)[0])
    station_map["station_id"] = station_map["station_id"].astype(str)
    station_map["zone_id"] = normalize_zone_id(station_map["zone_id"])
    chunk_groups = []
    usecols = [
        "ride_id",
        "started_at",
        "start_station_id",
        "member_casual",
    ]
    for path in bike_paths:
        for bike in iter_csv_chunks(path, chunksize=500_000, usecols=lambda c: c in usecols):
            bike["start_station_id"] = bike["start_station_id"].astype(str)
            bike["hour"] = parse_hour(bike["started_at"])
            bike = bike.merge(
                station_map,
                left_on="start_station_id",
                right_on="station_id",
                how="left",
            )
            bike["zone_id"] = bike["zone_id"].fillna("unknown")
            bike["is_member"] = bike.get("member_casual", "").astype(str).str.lower().eq("member")
            bike["is_casual"] = bike.get("member_casual", "").astype(str).str.lower().eq("casual")
            bike["is_peak"] = bike["hour"].dt.hour.isin([7, 8, 9, 16, 17, 18])
            chunk_groups.append(
                bike.dropna(subset=["hour"])
                .groupby(["zone_id", "hour"], as_index=False)
                .agg(
                    bike_trip_count=("ride_id", "count"),
                    bike_member_count=("is_member", "sum"),
                    bike_casual_count=("is_casual", "sum"),
                    bike_peak_count=("is_peak", "sum"),
                )
            )
    if not chunk_groups:
        return pd.DataFrame(
            columns=[
                "zone_id",
                "hour",
                "bike_trip_count",
                "bike_member_count",
                "bike_casual_count",
                "bike_peak_count",
            ]
        )
    grouped = pd.concat(chunk_groups, ignore_index=True)
    return (
        grouped.groupby(["zone_id", "hour"], as_index=False)
        .agg(
            bike_trip_count=("bike_trip_count", "sum"),
            bike_member_count=("bike_member_count", "sum"),
            bike_casual_count=("bike_casual_count", "sum"),
            bike_peak_count=("bike_peak_count", "sum"),
        )
    )


def aggregate_taxi(sample: bool) -> pd.DataFrame:
    taxi = read_many(require_paths("taxi", sample=sample))
    pickup_candidates = ["pickup_datetime", "tpep_pickup_datetime", "lpep_pickup_datetime"]
    present_pickup_cols = [col for col in pickup_candidates if col in taxi.columns]
    if not present_pickup_cols:
        raise KeyError(f"None of the pickup datetime columns exist: {pickup_candidates}")
    pickup = pd.Series(pd.NaT, index=taxi.index, dtype="datetime64[ns]")
    for col in present_pickup_cols:
        parsed = pd.to_datetime(taxi[col], errors="coerce")
        pickup = pickup.fillna(parsed)
    taxi["hour"] = pickup.dt.floor("h")
    taxi["zone_id"] = normalize_zone_id(taxi["PULocationID"])
    value_cols = {}
    if "trip_distance" in taxi.columns:
        value_cols["taxi_mean_distance"] = ("trip_distance", "mean")
    if "total_amount" in taxi.columns:
        value_cols["taxi_mean_total_amount"] = ("total_amount", "mean")
    grouped = (
        taxi.dropna(subset=["hour"])
        .groupby(["zone_id", "hour"], as_index=False)
        .agg(taxi_pickup_count=("PULocationID", "count"), **value_cols)
    )
    return grouped


def aggregate_mta(sample: bool) -> pd.DataFrame:
    mta = read_many(require_paths("mta", sample=sample))
    station_map = read_table(require_paths("mta_station_zone_map", sample=sample)[0])
    station_map["station_complex_id"] = station_map["station_complex_id"].astype(str)
    station_map["zone_id"] = normalize_zone_id(station_map["zone_id"])

    timestamp_col = first_existing_column(mta, ["transit_timestamp", "timestamp", "hour"])
    station_col = first_existing_column(mta, ["station_complex_id", "station_id"])
    ridership_col = first_existing_column(mta, ["ridership", "riders", "entries"])
    mta["hour"] = parse_hour(mta[timestamp_col])
    mta[station_col] = mta[station_col].astype(str)
    mta = mta.merge(
        station_map,
        left_on=station_col,
        right_on="station_complex_id",
        how="left",
    )
    mta["zone_id"] = mta["zone_id"].fillna("unknown")
    grouped = (
        mta.dropna(subset=["hour"])
        .groupby(["zone_id", "hour"], as_index=False)
        .agg(subway_ridership=("ridership", "sum"))
        if ridership_col == "ridership"
        else mta.dropna(subset=["hour"])
        .rename(columns={ridership_col: "ridership"})
        .groupby(["zone_id", "hour"], as_index=False)
        .agg(subway_ridership=("ridership", "sum"))
    )
    return grouped


def aggregate_bus(sample: bool) -> pd.DataFrame:
    bus_paths = resolve_manifest_paths("bus", sample=sample)
    if not bus_paths:
        return pd.DataFrame(columns=["zone_id", "hour", "bus_ridership", "bus_transfer_count"])

    map_paths = resolve_manifest_paths("bus_route_zone_map", sample=sample)
    if not map_paths:
        raise FileNotFoundError(
            "Bus ridership files were found, but no bus_route_zone_map file is available. "
            "Expected columns: bus_route, zone_id, allocation_weight."
        )

    bus = read_many(bus_paths)
    route_map = read_table(map_paths[0])
    timestamp_col = first_existing_column(bus, ["transit_timestamp", "timestamp", "hour"])
    route_col = first_existing_column(bus, ["bus_route", "route_id", "route"])
    ridership_col = first_existing_column(bus, ["ridership", "riders"])

    bus["hour"] = parse_hour(bus[timestamp_col])
    bus["bus_route"] = bus[route_col].astype(str).str.upper().str.strip()
    bus["ridership"] = pd.to_numeric(bus[ridership_col], errors="coerce").fillna(0.0)
    if "transfers" in bus.columns:
        bus["transfers"] = pd.to_numeric(bus["transfers"], errors="coerce").fillna(0.0)
    else:
        bus["transfers"] = 0.0

    route_map["bus_route"] = route_map["bus_route"].astype(str).str.upper().str.strip()
    route_map["zone_id"] = normalize_zone_id(route_map["zone_id"])
    if "allocation_weight" not in route_map.columns:
        route_map["allocation_weight"] = 1.0
    route_map["allocation_weight"] = pd.to_numeric(route_map["allocation_weight"], errors="coerce").fillna(0.0)
    route_totals = route_map.groupby("bus_route")["allocation_weight"].transform("sum")
    route_map["allocation_weight"] = route_map["allocation_weight"] / route_totals.replace(0, 1)

    route_hour = (
        bus.dropna(subset=["hour"])
        .groupby(["bus_route", "hour"], as_index=False)
        .agg(ridership=("ridership", "sum"), transfers=("transfers", "sum"))
    )
    allocated = route_hour.merge(route_map, on="bus_route", how="left")
    allocated["zone_id"] = allocated["zone_id"].fillna("unknown")
    allocated["allocation_weight"] = allocated["allocation_weight"].fillna(0.0)
    allocated["bus_ridership"] = allocated["ridership"] * allocated["allocation_weight"]
    allocated["bus_transfer_count"] = allocated["transfers"] * allocated["allocation_weight"]
    return (
        allocated.groupby(["zone_id", "hour"], as_index=False)
        .agg(bus_ridership=("bus_ridership", "sum"), bus_transfer_count=("bus_transfer_count", "sum"))
    )


def aggregate_weather(sample: bool) -> pd.DataFrame:
    weather = read_many(require_paths("weather", sample=sample))
    time_col = first_existing_column(weather, ["time", "timestamp", "hour"])
    weather["hour"] = parse_hour(weather[time_col])
    for col in ["precipitation", "rain", "temperature_2m", "wind_speed_10m"]:
        if col not in weather.columns:
            weather[col] = 0.0
    return (
        weather.dropna(subset=["hour"])
        .groupby("hour", as_index=False)
        .agg(
            precipitation=("precipitation", "max"),
            rain=("rain", "max"),
            temperature_2m=("temperature_2m", "mean"),
            wind_speed_10m=("wind_speed_10m", "mean"),
        )
    )


def build_panel(sample: bool, output: Path) -> pd.DataFrame:
    ensure_dirs()
    bike = aggregate_bike(sample)
    taxi = aggregate_taxi(sample)
    mta = aggregate_mta(sample)
    bus = aggregate_bus(sample)
    weather = aggregate_weather(sample)

    panel = bike.merge(taxi, on=["zone_id", "hour"], how="outer")
    panel = panel.merge(mta, on=["zone_id", "hour"], how="outer")
    panel = panel.merge(bus, on=["zone_id", "hour"], how="outer")
    zones = sorted(z for z in panel["zone_id"].dropna().unique() if z != "unknown")
    hours = sorted(weather["hour"].dropna().unique())
    base = pd.MultiIndex.from_product([zones, hours], names=["zone_id", "hour"]).to_frame(index=False)
    panel = base.merge(panel, on=["zone_id", "hour"], how="left")
    panel = panel.merge(weather, on="hour", how="left")
    count_cols = [
        "bike_trip_count",
        "bike_member_count",
        "bike_casual_count",
        "bike_peak_count",
        "taxi_pickup_count",
        "subway_ridership",
    ]
    for col in count_cols:
        panel[col] = panel[col].fillna(0).astype(int)
    for col in [
        "bus_ridership",
        "bus_transfer_count",
        "taxi_mean_distance",
        "taxi_mean_total_amount",
        "precipitation",
        "rain",
        "temperature_2m",
        "wind_speed_10m",
    ]:
        if col in panel.columns:
            panel[col] = panel[col].fillna(0.0)
    panel = panel.sort_values(["hour", "zone_id"])
    output.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(output, index=False)
    return panel


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="store_true", help="Use bundled sample data.")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROCESSED_DIR / "panel_zone_hour.csv",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    panel = build_panel(args.sample, args.output)
    print(f"Wrote {args.output} rows={len(panel)} zones={panel['zone_id'].nunique()}")


if __name__ == "__main__":
    main()
