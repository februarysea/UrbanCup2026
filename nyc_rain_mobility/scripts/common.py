"""Shared utilities for the NYC rain mobility pipeline."""

from __future__ import annotations

import csv
import glob
import gzip
import json
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_DIR / "config"
DATA_DIR = PROJECT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
INTERIM_DIR = DATA_DIR / "interim"
PROCESSED_DIR = DATA_DIR / "processed"
SAMPLE_DIR = DATA_DIR / "sample"
PRESENTATION_DIR = PROJECT_DIR / "presentation"
TABLES_DIR = PRESENTATION_DIR / "tables"


def ensure_dirs() -> None:
    for path in [RAW_DIR, INTERIM_DIR, PROCESSED_DIR, TABLES_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def read_manifest() -> dict[str, Any]:
    return load_json(CONFIG_DIR / "raw_data_manifest.json")


def read_pipeline_config() -> dict[str, Any]:
    return load_json(CONFIG_DIR / "pipeline_config.json")


def resolve_manifest_paths(key: str, *, sample: bool) -> list[Path]:
    manifest = read_manifest()
    if key not in manifest:
        raise KeyError(f"Unknown manifest key: {key}")
    pattern_key = "sample_glob" if sample else "raw_glob"
    pattern = manifest[key][pattern_key]
    root = PROJECT_DIR
    paths = [Path(p).resolve() for p in glob.glob(str(root / pattern))]
    return sorted(paths)


def require_paths(key: str, *, sample: bool) -> list[Path]:
    paths = resolve_manifest_paths(key, sample=sample)
    if not paths:
        mode = "sample" if sample else "raw"
        raise FileNotFoundError(f"No {mode} files found for manifest key {key!r}")
    return paths


def read_table(path: Path, **kwargs: Any) -> pd.DataFrame:
    suffixes = "".join(path.suffixes).lower()
    if suffixes.endswith(".parquet"):
        return pd.read_parquet(path, **kwargs)
    if suffixes.endswith(".csv") or suffixes.endswith(".csv.gz"):
        return pd.read_csv(path, **kwargs)
    if suffixes.endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            names = [name for name in zf.namelist() if name.lower().endswith(".csv")]
            if not names:
                raise ValueError(f"No CSV found inside {path}")
            frames = []
            for name in names:
                with zf.open(name) as raw:
                    frames.append(pd.read_csv(raw, **kwargs))
            return pd.concat(frames, ignore_index=True)
    raise ValueError(f"Unsupported table format: {path}")


def read_many(paths: list[Path], **kwargs: Any) -> pd.DataFrame:
    frames = [read_table(path, **kwargs) for path in paths]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def parse_hour(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce").dt.floor("h")


def normalize_zone_id(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def first_existing_column(df: pd.DataFrame, candidates: list[str]) -> str:
    for candidate in candidates:
        if candidate in df.columns:
            return candidate
    raise KeyError(f"None of the columns exist: {candidates}")


def iter_csv_dicts(path: Path):
    """Yield CSV rows from .csv, .csv.gz, or single/multi-file .zip archives."""
    suffixes = "".join(path.suffixes).lower()
    if suffixes.endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            names = [name for name in zf.namelist() if name.lower().endswith(".csv")]
            if not names:
                raise ValueError(f"No CSV found inside {path}")
            for name in names:
                with zf.open(name) as raw:
                    text = (line.decode("utf-8", errors="replace") for line in raw)
                    yield from csv.DictReader(text)
    elif suffixes.endswith(".csv.gz"):
        with gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="") as f:
            yield from csv.DictReader(f)
    elif suffixes.endswith(".csv"):
        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            yield from csv.DictReader(f)
    else:
        raise ValueError(f"Unsupported CSV stream format: {path}")


def iter_csv_chunks(path: Path, *, chunksize: int = 500_000, **kwargs: Any):
    """Yield pandas CSV chunks from .csv, .csv.gz, or .zip archives."""
    suffixes = "".join(path.suffixes).lower()
    if suffixes.endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            names = [name for name in zf.namelist() if name.lower().endswith(".csv")]
            if not names:
                raise ValueError(f"No CSV found inside {path}")
            for name in names:
                with zf.open(name) as raw:
                    yield from pd.read_csv(raw, chunksize=chunksize, **kwargs)
    elif suffixes.endswith(".csv") or suffixes.endswith(".csv.gz"):
        yield from pd.read_csv(path, chunksize=chunksize, **kwargs)
    else:
        raise ValueError(f"Unsupported CSV chunk format: {path}")
