#!/usr/bin/env python3
"""Build ACS socioeconomic features on TLC taxi zones.

The script downloads ACS 5-year tract variables for NYC, downloads Census tract
geometries, overlays tracts with TLC taxi zones, and writes taxi-zone-level
features used by synthetic agent generation.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pandas as pd
import requests
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform

from common import CONFIG_DIR, INTERIM_DIR, RAW_DIR, SAMPLE_DIR, normalize_zone_id, write_json


NYC_COUNTIES = {
    "005": "Bronx",
    "047": "Brooklyn",
    "061": "Manhattan",
    "081": "Queens",
    "085": "Staten Island",
}

ACS_VARIABLES = {
    "B01003_001E": "total_population",
    "B08301_001E": "commute_total",
    "B08301_010E": "public_transport_commuters",
    "B08301_016E": "taxi_commuters",
    "B08301_018E": "bike_commuters",
    "B08301_019E": "walk_commuters",
    "B08301_021E": "work_from_home_workers",
    "B08201_001E": "vehicle_households_total",
    "B08201_002E": "no_vehicle_households",
    "B17001_001E": "poverty_status_total",
    "B17001_002E": "poverty_below",
    "B19013_001E": "median_household_income",
    "B19001_001E": "income_households_total",
    "B08136_001E": "aggregate_commute_minutes",
}

LOW_INCOME_VARIABLES = {
    "B19001_002E": "income_under_10k",
    "B19001_003E": "income_10k_15k",
    "B19001_004E": "income_15k_20k",
    "B19001_005E": "income_20k_25k",
    "B19001_006E": "income_25k_30k",
    "B19001_007E": "income_30k_35k",
}

COUNT_COLUMNS = [
    "total_population",
    "commute_total",
    "public_transport_commuters",
    "taxi_commuters",
    "bike_commuters",
    "walk_commuters",
    "work_from_home_workers",
    "vehicle_households_total",
    "no_vehicle_households",
    "poverty_status_total",
    "poverty_below",
    "income_households_total",
    "low_income_households",
    "aggregate_commute_minutes",
]

RATE_OUTPUT_COLUMNS = [
    "no_vehicle_share",
    "transit_commute_share",
    "bike_commute_share",
    "walk_commute_share",
    "taxi_commute_share",
    "work_from_home_share",
    "poverty_share",
    "low_income_share",
    "avg_commute_time",
]


def _download_text(url: str, *, timeout: int = 90, retries: int = 3) -> str:
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            return response.text
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(2 * attempt)
    raise RuntimeError(f"Failed to download {url}: {last_exc}") from last_exc


def _download_json(url: str, *, timeout: int = 90, retries: int = 3) -> Any:
    return json.loads(_download_text(url, timeout=timeout, retries=retries))


def _clean_numeric(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    return values.mask(values <= -1_000_000)


def _safe_divide(numerator: float, denominator: float) -> float:
    if denominator is None or denominator == 0 or math.isnan(float(denominator)):
        return 0.0
    return float(numerator or 0.0) / float(denominator)


def _acs_endpoint_available(year: int, api_key: str | None) -> bool:
    url = (
        f"https://api.census.gov/data/{year}/acs/acs5"
        "?get=NAME,B01003_001E&for=tract:*&in=state:36%20county:061"
    )
    if api_key:
        url += f"&key={api_key}"
    try:
        payload = _download_json(url, timeout=30, retries=1)
        return isinstance(payload, list) and len(payload) > 1
    except Exception:
        return False


def choose_acs_year(preferred_year: int, fallback_years: list[int], api_key: str | None) -> int:
    for year in [preferred_year, *fallback_years]:
        if _acs_endpoint_available(year, api_key):
            return year
    tried = [preferred_year, *fallback_years]
    raise RuntimeError(f"No reachable ACS 5-year endpoint found for years: {tried}")


def fetch_acs_tracts(year: int, output: Path, api_key: str | None, force: bool = False) -> pd.DataFrame:
    if output.exists() and not force:
        return pd.read_csv(output, dtype={"state": str, "county": str, "tract": str, "geoid": str})

    variables = list(ACS_VARIABLES) + list(LOW_INCOME_VARIABLES)
    get_vars = ["NAME", *variables]
    frames = []
    for county in NYC_COUNTIES:
        params = {
            "get": ",".join(get_vars),
            "for": "tract:*",
            "in": f"state:36 county:{county}",
        }
        if api_key:
            params["key"] = api_key
        safe_chars = ":,*"
        query = "&".join(f"{key}={quote(str(value), safe=safe_chars)}" for key, value in params.items())
        url = f"https://api.census.gov/data/{year}/acs/acs5?{query}"
        payload = _download_json(url)
        header, rows = payload[0], payload[1:]
        frame = pd.DataFrame(rows, columns=header)
        frames.append(frame)

    acs = pd.concat(frames, ignore_index=True)
    acs["geoid"] = acs["state"].astype(str) + acs["county"].astype(str) + acs["tract"].astype(str)
    for variable, column in ACS_VARIABLES.items():
        acs[column] = _clean_numeric(acs[variable])
    low_income_cols = []
    for variable, column in LOW_INCOME_VARIABLES.items():
        acs[column] = _clean_numeric(acs[variable]).fillna(0.0)
        low_income_cols.append(column)
    acs["low_income_households"] = acs[low_income_cols].sum(axis=1)

    keep = ["geoid", "NAME", "state", "county", "tract", *ACS_VARIABLES.values(), "low_income_households"]
    acs = acs[keep]
    output.parent.mkdir(parents=True, exist_ok=True)
    acs.to_csv(output, index=False)
    return acs


def fetch_tract_geometries(year: int, output: Path, force: bool = False) -> dict[str, Any]:
    if output.exists() and not force:
        return json.loads(output.read_text(encoding="utf-8"))

    # TIGERweb returns current tract geometries and avoids downloading all NY State tracts.
    where = "STATE='36' AND COUNTY IN ('005','047','061','081','085')"
    base = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Tracts_Blocks/MapServer/0/query"
    params = {
        "where": where,
        "outFields": "GEOID,STATE,COUNTY,TRACT,NAME",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
        "resultRecordCount": "2000",
    }
    features: list[dict[str, Any]] = []
    offset = 0
    while True:
        params["resultOffset"] = str(offset)
        safe_chars = "',=()"
        query = "&".join(f"{key}={quote(str(value), safe=safe_chars)}" for key, value in params.items())
        payload = _download_json(f"{base}?{query}", timeout=120)
        batch = payload.get("features", [])
        features.extend(batch)
        if len(batch) < int(params["resultRecordCount"]):
            break
        offset += len(batch)

    if not features:
        raise RuntimeError("Census TIGERweb returned no NYC tract geometries.")
    geojson = {"type": "FeatureCollection", "features": features, "metadata": {"source": base, "year_requested": year}}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(geojson), encoding="utf-8")
    return geojson


def _feature_property(props: dict[str, Any], candidates: list[str]) -> str:
    lower_lookup = {str(key).lower(): value for key, value in props.items()}
    for candidate in candidates:
        if candidate.lower() in lower_lookup:
            return str(lower_lookup[candidate.lower()])
    raise KeyError(f"None of these properties exist: {candidates}. Available: {sorted(props)}")


def load_taxi_zone_geometries(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:2263", always_xy=True)
    zones = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        zone_id = _feature_property(props, ["locationid", "LocationID", "zone_id", "objectid"])
        geom = transform(transformer.transform, shape(feature["geometry"]))
        if geom.is_empty:
            continue
        zones.append(
            {
                "zone_id": str(zone_id).strip(),
                "borough": props.get("borough") or props.get("Borough") or "",
                "zone_name": props.get("zone") or props.get("Zone") or "",
                "geometry": geom,
                "area": geom.area,
            }
        )
    return zones


def load_tract_geometries(geojson: dict[str, Any]) -> list[dict[str, Any]]:
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:2263", always_xy=True)
    tracts = []
    county_prefixes = {f"36{county}" for county in NYC_COUNTIES}
    for feature in geojson.get("features", []):
        props = feature.get("properties", {})
        geoid = _feature_property(props, ["GEOID", "geoid"])
        if not any(geoid.startswith(prefix) for prefix in county_prefixes):
            continue
        geom = transform(transformer.transform, shape(feature["geometry"]))
        if geom.is_empty or geom.area <= 0:
            continue
        tracts.append({"geoid": geoid, "geometry": geom, "area": geom.area})
    return tracts


def interpolate_to_taxi_zones(acs: pd.DataFrame, tracts: list[dict[str, Any]], zones: list[dict[str, Any]]) -> pd.DataFrame:
    acs_lookup = acs.set_index("geoid").to_dict(orient="index")
    accum: dict[str, dict[str, float | str]] = {
        zone["zone_id"]: {
            "zone_id": zone["zone_id"],
            "borough": zone["borough"],
            "zone_name": zone["zone_name"],
            "tract_overlap_area": 0.0,
        }
        for zone in zones
    }
    for zone_id in accum:
        for col in COUNT_COLUMNS:
            accum[zone_id][col] = 0.0
        accum[zone_id]["median_income_weighted_sum"] = 0.0
        accum[zone_id]["median_income_weight"] = 0.0

    for tract in tracts:
        tract_row = acs_lookup.get(tract["geoid"])
        if not tract_row:
            continue
        tract_geom = tract["geometry"]
        tract_area = float(tract["area"])
        if tract_area <= 0:
            continue
        for zone in zones:
            if not tract_geom.intersects(zone["geometry"]):
                continue
            overlap_area = tract_geom.intersection(zone["geometry"]).area
            if overlap_area <= 0:
                continue
            weight = overlap_area / tract_area
            target = accum[zone["zone_id"]]
            target["tract_overlap_area"] = float(target["tract_overlap_area"]) + overlap_area
            for col in COUNT_COLUMNS:
                value = tract_row.get(col)
                if pd.notna(value):
                    target[col] = float(target[col]) + float(value) * weight
            income = tract_row.get("median_household_income")
            household_weight = tract_row.get("income_households_total")
            if pd.notna(income) and pd.notna(household_weight) and float(household_weight) > 0:
                target["median_income_weighted_sum"] = float(target["median_income_weighted_sum"]) + float(income) * float(household_weight) * weight
                target["median_income_weight"] = float(target["median_income_weight"]) + float(household_weight) * weight

    rows = []
    for zone_id, row in accum.items():
        median_income = _safe_divide(float(row["median_income_weighted_sum"]), float(row["median_income_weight"]))
        commute_total = float(row["commute_total"])
        non_wfh_workers = max(commute_total - float(row["work_from_home_workers"]), 0.0)
        out = {
            "zone_id": zone_id,
            "borough": row["borough"],
            "zone_name": row["zone_name"],
            "total_population": round(float(row["total_population"]), 3),
            "worker_population": round(commute_total, 3),
            "household_count": round(float(row["income_households_total"]), 3),
            "median_household_income": round(median_income, 3),
            "no_vehicle_share": round(_safe_divide(float(row["no_vehicle_households"]), float(row["vehicle_households_total"])), 6),
            "transit_commute_share": round(_safe_divide(float(row["public_transport_commuters"]), commute_total), 6),
            "bike_commute_share": round(_safe_divide(float(row["bike_commuters"]), commute_total), 6),
            "walk_commute_share": round(_safe_divide(float(row["walk_commuters"]), commute_total), 6),
            "taxi_commute_share": round(_safe_divide(float(row["taxi_commuters"]), commute_total), 6),
            "work_from_home_share": round(_safe_divide(float(row["work_from_home_workers"]), commute_total), 6),
            "poverty_share": round(_safe_divide(float(row["poverty_below"]), float(row["poverty_status_total"])), 6),
            "low_income_share": round(_safe_divide(float(row["low_income_households"]), float(row["income_households_total"])), 6),
            "avg_commute_time": round(_safe_divide(float(row["aggregate_commute_minutes"]), non_wfh_workers), 3),
        }
        rows.append(out)

    output = pd.DataFrame(rows)
    for col in RATE_OUTPUT_COLUMNS:
        output[col] = output[col].fillna(0.0).clip(lower=0.0)
    return output.sort_values("zone_id")


def build_acs_zone_features(
    year: int,
    fallback_years: list[int],
    taxi_zones_path: Path,
    output: Path,
    interim_dir: Path,
    force: bool = False,
    api_key: str | None = None,
) -> pd.DataFrame:
    api_key = api_key or os.environ.get("CENSUS_API_KEY")
    acs_year = choose_acs_year(year, fallback_years, api_key)
    acs_path = interim_dir / f"acs5_tract_nyc_{acs_year}.csv"
    tract_geojson_path = interim_dir / f"census_tracts_nyc_{acs_year}.geojson"
    metadata_path = output.with_suffix(".metadata.json")

    acs = fetch_acs_tracts(acs_year, acs_path, api_key, force=force)
    tract_geojson = fetch_tract_geometries(acs_year, tract_geojson_path, force=force)
    taxi_zones = load_taxi_zone_geometries(taxi_zones_path)
    tracts = load_tract_geometries(tract_geojson)
    features = interpolate_to_taxi_zones(acs, tracts, taxi_zones)
    features["acs_year"] = acs_year
    features["interpolation_method"] = "tract_area_weighted_to_taxi_zone_epsg2263"
    features["acs_source"] = f"https://api.census.gov/data/{acs_year}/acs/acs5"

    output.parent.mkdir(parents=True, exist_ok=True)
    features.to_csv(output, index=False)
    write_json(
        metadata_path,
        {
            "acs_year": acs_year,
            "requested_year": year,
            "fallback_years": fallback_years,
            "taxi_zones_path": str(taxi_zones_path),
            "output": str(output),
            "tract_count": len(tracts),
            "taxi_zone_count": len(taxi_zones),
            "output_rows": len(features),
            "method": "Area-weighted tract-to-taxi-zone interpolation in EPSG:2263. Count variables are allocated by overlap area; median household income is household-weighted after allocation.",
        },
    )
    return features


def _sample_rate(row: pd.Series, column: str, default: float = 0.0) -> float:
    value = row.get(column, default)
    if pd.isna(value):
        return default
    return float(value)


def build_sample_acs_zone_features(taxi_zones_path: Path, sample_acs_path: Path, output: Path) -> pd.DataFrame:
    """Offline fixture that exercises the same interpolation path without Census network access."""
    zones = load_taxi_zone_geometries(taxi_zones_path)
    sample = pd.read_csv(sample_acs_path)
    sample["zone_id"] = normalize_zone_id(sample["zone_id"])
    sample_lookup = sample.set_index("zone_id").to_dict(orient="index")

    tracts = []
    acs_rows = []
    for idx, zone in enumerate(zones, start=1):
        geoid = f"360610{idx:05d}"
        src = pd.Series(sample_lookup.get(zone["zone_id"], {}))
        total_population = 10_000 + idx * 500
        commute_total = 4_800 + idx * 250
        household_total = 4_000 + idx * 180
        wfh_share = 0.10
        avg_commute_time = _sample_rate(src, "avg_commute_time", 35.0)
        work_from_home_workers = commute_total * wfh_share
        tracts.append({"geoid": geoid, "geometry": zone["geometry"], "area": zone["area"]})
        acs_rows.append(
            {
                "geoid": geoid,
                "NAME": f"Sample tract for taxi zone {zone['zone_id']}",
                "state": "36",
                "county": "061",
                "tract": f"{idx:06d}",
                "total_population": total_population,
                "commute_total": commute_total,
                "public_transport_commuters": commute_total * _sample_rate(src, "transit_commute_share", 0.5),
                "taxi_commuters": commute_total * 0.015,
                "bike_commuters": commute_total * _sample_rate(src, "bike_commute_share", 0.02),
                "walk_commuters": commute_total * _sample_rate(src, "walk_commute_share", 0.12),
                "work_from_home_workers": work_from_home_workers,
                "vehicle_households_total": household_total,
                "no_vehicle_households": household_total * _sample_rate(src, "no_vehicle_share", 0.5),
                "poverty_status_total": total_population,
                "poverty_below": total_population * _sample_rate(src, "poverty_share", 0.2),
                "median_household_income": _sample_rate(src, "median_household_income", 75_000),
                "income_households_total": household_total,
                "low_income_households": household_total * _sample_rate(src, "low_income_share", 0.25),
                "aggregate_commute_minutes": avg_commute_time * max(commute_total - work_from_home_workers, 1.0),
            }
        )

    features = interpolate_to_taxi_zones(pd.DataFrame(acs_rows), tracts, zones)
    features["acs_year"] = "sample"
    features["interpolation_method"] = "sample_tract_area_weighted_to_taxi_zone_epsg2263"
    features["acs_source"] = str(sample_acs_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    features.to_csv(output, index=False)
    write_json(
        output.with_suffix(".metadata.json"),
        {
            "sample": True,
            "taxi_zones_path": str(taxi_zones_path),
            "sample_acs_path": str(sample_acs_path),
            "output": str(output),
            "output_rows": len(features),
            "method": "Offline sample fixture using taxi-zone-shaped synthetic tracts; validates the interpolation and output schema without Census network access.",
        },
    )
    return features


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="store_true", help="Run an offline sample build without Census network access.")
    parser.add_argument("--year", type=int, default=2024, help="Preferred ACS 5-year release year.")
    parser.add_argument(
        "--fallback-years",
        type=int,
        nargs="*",
        default=[2023, 2022, 2021],
        help="Fallback ACS years if the preferred endpoint is unavailable.",
    )
    parser.add_argument(
        "--taxi-zones",
        type=Path,
        default=RAW_DIR / "taxi_zones.geojson",
        help="TLC taxi zone GeoJSON path. Download with download_real_data.py --datasets zones --execute.",
    )
    parser.add_argument("--output", type=Path, default=CONFIG_DIR / "acs_zone_features.csv")
    parser.add_argument("--interim-dir", type=Path, default=INTERIM_DIR / "census")
    parser.add_argument("--force", action="store_true", help="Re-download cached ACS and tract geometry files.")
    parser.add_argument("--api-key", default=None, help="Optional Census API key. Defaults to CENSUS_API_KEY env var.")
    parser.add_argument("--sample-acs", type=Path, default=SAMPLE_DIR / "acs_zone_features.csv")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.sample and args.taxi_zones == RAW_DIR / "taxi_zones.geojson":
        args.taxi_zones = SAMPLE_DIR / "taxi_zones.geojson"
    if not args.taxi_zones.exists():
        raise FileNotFoundError(
            f"Taxi zone file not found: {args.taxi_zones}. "
            "Run scripts/download_real_data.py --datasets zones --execute first."
        )
    if args.sample:
        features = build_sample_acs_zone_features(args.taxi_zones, args.sample_acs, args.output)
    else:
        features = build_acs_zone_features(
            year=args.year,
            fallback_years=args.fallback_years,
            taxi_zones_path=args.taxi_zones,
            output=args.output,
            interim_dir=args.interim_dir,
            force=args.force,
            api_key=args.api_key,
        )
    print(f"Wrote {args.output} rows={len(features)} columns={len(features.columns)}")
    print(features.head().to_string(index=False))


if __name__ == "__main__":
    main()
