#!/usr/bin/env python3
"""Create a lightweight Urban Cup submission bundle."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_DIR.parent
TABLES_DIR = PROJECT_DIR / "presentation" / "tables"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "submission_bundle"


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def safe_component(value: str) -> str:
    chars = []
    for char in value.strip():
        if char.isalnum() or char in "._-":
            chars.append(char)
        elif char.isspace() or char in "/\\:：":
            chars.append("_")
        else:
            chars.append("_")
    return "".join(chars).strip("_") or "submission"


def run_git(args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=WORKSPACE_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except Exception:
        return None
    return result.stdout.strip()


def git_info() -> dict[str, Any]:
    status = run_git(["status", "--short"]) or ""
    return {
        "commit": run_git(["rev-parse", "HEAD"]),
        "branch": run_git(["branch", "--show-current"]),
        "remote_origin": run_git(["remote", "get-url", "origin"]),
        "dirty": bool(status),
        "status_short": status.splitlines(),
    }


def copy_file(src: Path, dst: Path, copied: list[str], *, required: bool = True) -> None:
    if not src.exists():
        if required:
            raise FileNotFoundError(src)
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    copied.append(str(dst))


def copy_tree(src: Path, dst: Path, copied: list[str], *, required: bool = True) -> None:
    if not src.exists():
        if required:
            raise FileNotFoundError(src)
        return
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")
    shutil.copytree(src, dst, ignore=ignore)
    for path in sorted(dst.rglob("*")):
        if path.is_file():
            copied.append(str(path))


def copy_init_configs(dst_root: Path, copied: list[str]) -> None:
    source_root = PROJECT_DIR / "hypothesis_1"
    for init_dir in sorted(source_root.glob("*/init")):
        rel = init_dir.relative_to(PROJECT_DIR)
        copy_tree(init_dir, dst_root / rel, copied)


def copy_optional_outputs(dst_root: Path, copied: list[str], *, include_processed_panel: bool) -> None:
    table_dst = dst_root / "evidence" / "tables"
    for path in sorted(TABLES_DIR.glob("*")):
        if path.is_file() and path.name != ".gitkeep":
            copy_file(path, table_dst / path.name, copied, required=False)

    processed_dst = dst_root / "evidence" / "processed"
    for name in ["rain_events.json"]:
        copy_file(PROJECT_DIR / "data" / "processed" / name, processed_dst / name, copied, required=False)

    if include_processed_panel:
        for name in ["panel_zone_hour.csv", "panel_labeled.csv"]:
            copy_file(PROJECT_DIR / "data" / "processed" / name, processed_dst / name, copied, required=False)


def write_submission_readme(
    bundle_dir: Path,
    *,
    report_base: str,
    include_processed_panel: bool,
) -> None:
    text = f"""# Urban Cup 2026 Submission Bundle

Primary report: `{report_base}.md`

## Contents

- `agentsociety_workspace/`: lightweight workspace to reproduce the experiment code, custom environment, sample data, and generated AgentSociety2 init configs.
- `evidence/`: current generated tables and rain-event evidence from the latest local run.
- `manifest.json`: Git commit, generation timestamp, included files, and validation metadata.

## Reproduce

```bash
cd agentsociety_workspace
python nyc_rain_mobility/run_pipeline.py --sample --stage all
AGENTSOCIETY_LLM_API_KEY=test-key python nyc_rain_mobility/run_pipeline.py --sample --stage validate
```

For the full data run, first use:

```bash
python nyc_rain_mobility/scripts/download_real_data.py --year 2024 --months 7 --execute
python nyc_rain_mobility/scripts/generate_zone_maps.py
python nyc_rain_mobility/run_pipeline.py --stage all
```

Raw NYC mobility files are intentionally not bundled because they are public and large.
Processed panel files included: `{include_processed_panel}`.
"""
    (bundle_dir / "README_SUBMISSION.md").write_text(text, encoding="utf-8")


def create_zip(bundle_dir: Path) -> Path:
    zip_path = bundle_dir.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(bundle_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(bundle_dir.parent))
    return zip_path


def build_bundle(args: argparse.Namespace) -> tuple[Path, Path | None]:
    report_base = safe_component(f"{args.competition}_{args.team_name}_{args.work_name}")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bundle_dir = args.output_dir / f"{report_base}_{timestamp}"
    if bundle_dir.exists():
        raise FileExistsError(bundle_dir)

    copied: list[str] = []
    workspace_dst = bundle_dir / "agentsociety_workspace"
    project_dst = workspace_dst / "nyc_rain_mobility"

    copy_file(WORKSPACE_ROOT / "README.md", workspace_dst / "README.md", copied, required=False)
    copy_file(WORKSPACE_ROOT / ".gitignore", workspace_dst / ".gitignore", copied, required=False)
    copy_tree(
        WORKSPACE_ROOT / ".agentsociety" / "env_modules",
        workspace_dst / ".agentsociety" / "env_modules",
        copied,
    )
    copy_tree(WORKSPACE_ROOT / "custom", workspace_dst / "custom", copied)

    for name in [
        "README.md",
        "README_REPRODUCE.md",
        "TOPIC.md",
        "HYPOTHESIS.md",
        "data_description.md",
        "requirements.txt",
        "run_pipeline.py",
    ]:
        copy_file(PROJECT_DIR / name, project_dst / name, copied)

    for directory in ["config", "scripts", "custom", "data/sample", "presentation/charts"]:
        copy_tree(PROJECT_DIR / directory, project_dst / directory, copied)

    copy_file(
        PROJECT_DIR / "presentation" / "report.md",
        bundle_dir / f"{report_base}.md",
        copied,
    )
    copy_file(
        PROJECT_DIR / "presentation" / "report.md",
        project_dst / "presentation" / "report.md",
        copied,
    )
    copy_init_configs(project_dst, copied)
    copy_optional_outputs(bundle_dir, copied, include_processed_panel=args.include_processed_panel)
    write_submission_readme(
        bundle_dir,
        report_base=report_base,
        include_processed_panel=args.include_processed_panel,
    )

    validation_summary_path = TABLES_DIR / "validation_summary.json"
    validation_summary = None
    if validation_summary_path.exists():
        validation_summary = json.loads(validation_summary_path.read_text(encoding="utf-8"))

    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "competition": args.competition,
        "team_name": args.team_name,
        "work_name": args.work_name,
        "report_file": f"{report_base}.md",
        "git": git_info(),
        "validation_summary": validation_summary,
        "file_count": len(copied),
        "files": sorted(str(Path(path).relative_to(bundle_dir)) for path in copied),
        "notes": [
            "Raw public mobility files are not bundled.",
            "Run download_real_data.py to fetch full NYC public datasets.",
            "Set AGENTSOCIETY_LLM_API_KEY before running LLM-backed AgentSociety2 scenarios.",
        ],
    }
    write_json(bundle_dir / "manifest.json", manifest)

    zip_path = create_zip(bundle_dir) if args.zip else None
    return bundle_dir, zip_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--competition", default="event3")
    parser.add_argument("--team-name", default="team_name")
    parser.add_argument("--work-name", default="nyc_rain_mobility")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--include-processed-panel",
        action="store_true",
        help="Also include panel_zone_hour.csv and panel_labeled.csv. Keep off for large real-data runs.",
    )
    parser.add_argument("--zip", action="store_true", help="Also create a zip archive.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    bundle_dir, zip_path = build_bundle(args)
    print(f"Wrote submission bundle: {bundle_dir}")
    if zip_path:
        print(f"Wrote archive: {zip_path}")


if __name__ == "__main__":
    main()
