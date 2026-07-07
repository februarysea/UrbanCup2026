#!/usr/bin/env python3
"""Download or list public NYC mobility/weather datasets for the rain experiment.

Default behavior is dry-run. Add --execute to actually download files.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from typing import Iterable

from common import RAW_DIR, ensure_dirs


TRIPDATA_BUCKET = "https://s3.amazonaws.com/tripdata"
TLC_BASE = "https://d37ci6vzurychx.cloudfront.net"
MTA_ENDPOINT = "https://data.ny.gov/resource/wujg-7c2s.csv"
OPEN_METEO_ENDPOINT = "https://archive-api.open-meteo.com/v1/archive"
TAXI_ZONES_GEOJSON = "https://data.cityofnewyork.us/resource/8meu-9t5y.geojson?$limit=5000"
NYC_LAT = 40.7128
NYC_LON = -74.0060


def _month_range(year: int, months: list[int]) -> tuple[str, str]:
    start = date(year, min(months), 1)
    end_month = max(months)
    if end_month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, end_month + 1, 1)
        end = date.fromordinal(end.toordinal() - 1)
    return start.isoformat(), end.isoformat()


def _head(url: str) -> tuple[int | None, int | None]:
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            length = response.headers.get("Content-Length")
            return response.status, int(length) if length else None
    except Exception:
        return None, None


def _download(url: str, output: Path, *, execute: bool) -> None:
    status, size = _head(url)
    size_label = f"{size / 1024 / 1024:.1f} MiB" if size else "unknown size"
    print(f"{'DOWNLOAD' if execute else 'DRY-RUN '} {url}")
    print(f"  -> {output} status={status} size={size_label}")
    if not execute:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as response, output.open("wb") as f:
        total = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
            total += len(chunk)
            if total % (100 * 1024 * 1024) < 1024 * 1024:
                print(f"    {total / 1024 / 1024:.0f} MiB", flush=True)


def _citibike_key(year: int, month: int) -> str:
    prefix = f"{year}{month:02d}"
    list_url = f"{TRIPDATA_BUCKET}?list-type=2&prefix={prefix}"
    with urllib.request.urlopen(list_url, timeout=30) as response:
        xml_text = response.read()
    root = ET.fromstring(xml_text)
    ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
    keys = [node.text or "" for node in root.findall(".//s3:Key", ns)]
    candidates = [
        key
        for key in keys
        if "citibike-tripdata" in key.lower()
        and key.lower().endswith(".zip")
        and not key.startswith("JC-")
    ]
    if not candidates:
        raise FileNotFoundError(f"No NYC Citi Bike key found for prefix {prefix}")
    return sorted(candidates, key=len)[0]


def _citibike_urls(year: int, months: list[int]) -> Iterable[tuple[str, Path]]:
    for month in months:
        key = _citibike_key(year, month)
        url = f"{TRIPDATA_BUCKET}/{urllib.parse.quote(key)}"
        yield url, RAW_DIR / key


def _tlc_urls(year: int, months: list[int], taxi_types: list[str]) -> Iterable[tuple[str, Path]]:
    for taxi_type in taxi_types:
        for month in months:
            filename = f"{taxi_type}_tripdata_{year}-{month:02d}.parquet"
            yield f"{TLC_BASE}/trip-data/{filename}", RAW_DIR / filename


def _taxi_zone_url() -> tuple[str, Path]:
    return TAXI_ZONES_GEOJSON, RAW_DIR / "taxi_zones.geojson"


def _weather_url(year: int, months: list[int]) -> tuple[str, Path]:
    start, end = _month_range(year, months)
    query = urllib.parse.urlencode(
        {
            "latitude": NYC_LAT,
            "longitude": NYC_LON,
            "start_date": start,
            "end_date": end,
            "hourly": "precipitation,rain,temperature_2m,wind_speed_10m",
            "timezone": "America/New_York",
        }
    )
    return f"{OPEN_METEO_ENDPOINT}?{query}", RAW_DIR / f"weather_hourly_{start}_{end}.csv"


def _download_weather(url: str, output: Path, *, execute: bool) -> None:
    print(f"{'DOWNLOAD' if execute else 'DRY-RUN '} {url}")
    print(f"  -> {output}")
    if not execute:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))
    hourly = payload["hourly"]
    rows = []
    for idx, timestamp in enumerate(hourly["time"]):
        rows.append(
            {
                "time": timestamp,
                "precipitation": hourly.get("precipitation", [0])[idx],
                "rain": hourly.get("rain", [0])[idx],
                "temperature_2m": hourly.get("temperature_2m", [0])[idx],
                "wind_speed_10m": hourly.get("wind_speed_10m", [0])[idx],
            }
        )
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["time", "precipitation", "rain", "temperature_2m", "wind_speed_10m"],
        )
        writer.writeheader()
        writer.writerows(rows)


def _mta_url(year: int, months: list[int]) -> tuple[str, Path]:
    start, end = _month_range(year, months)
    next_day = date.fromisoformat(end).toordinal() + 1
    end_exclusive = date.fromordinal(next_day).isoformat()
    where = (
        "transit_mode='subway' "
        f"AND transit_timestamp between '{start}T00:00:00' and '{end_exclusive}T00:00:00'"
    )
    select = (
        "transit_timestamp,station_complex_id,station_complex,borough,"
        "latitude,longitude,sum(ridership) as ridership"
    )
    params = {
        "$select": select,
        "$where": where,
        "$group": "transit_timestamp,station_complex_id,station_complex,borough,latitude,longitude",
        "$order": "transit_timestamp,station_complex_id",
        "$limit": "5000000",
    }
    return f"{MTA_ENDPOINT}?{urllib.parse.urlencode(params)}", RAW_DIR / f"mta_hourly_{start}_{end}.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--months", type=int, nargs="+", default=[6, 7, 8, 9])
    parser.add_argument(
        "--datasets",
        nargs="+",
        choices=["citibike", "yellow", "green", "fhvhv", "mta", "weather", "zones"],
        default=["citibike", "yellow", "green", "mta", "weather", "zones"],
    )
    parser.add_argument("--execute", action="store_true", help="Actually download files.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_dirs()
    months = sorted(set(args.months))
    jobs: list[tuple[str, Path, str]] = []

    if "citibike" in args.datasets:
        jobs.extend((url, path, "binary") for url, path in _citibike_urls(args.year, months))
    taxi_types = [name for name in ["yellow", "green", "fhvhv"] if name in args.datasets]
    if taxi_types:
        jobs.extend((url, path, "binary") for url, path in _tlc_urls(args.year, months, taxi_types))
    if "mta" in args.datasets:
        url, path = _mta_url(args.year, months)
        jobs.append((url, path, "binary"))
    if "weather" in args.datasets:
        url, path = _weather_url(args.year, months)
        jobs.append((url, path, "weather"))
    if "zones" in args.datasets:
        url, path = _taxi_zone_url()
        jobs.append((url, path, "binary"))

    for url, path, kind in jobs:
        if kind == "weather":
            _download_weather(url, path, execute=args.execute)
        else:
            _download(url, path, execute=args.execute)

    if not args.execute:
        print("\nDry-run only. Re-run with --execute to download.")
        print("Large warning: Citi Bike monthly NYC files can be close to or above 1 GiB each.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)

