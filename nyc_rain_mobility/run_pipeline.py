#!/usr/bin/env python3
"""Run the NYC rain mobility pipeline."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = PROJECT_DIR / "scripts"


STAGES = [
    "build-panel",
    "identify-events",
    "empirical",
    "agents",
    "configs",
    "simulate",
    "metrics",
    "report",
    "validate",
]
OPTIONAL_STAGES = ["census"]


def run_script(script_name: str, args: list[str]) -> None:
    cmd = [sys.executable, str(SCRIPTS_DIR / script_name), *args]
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=PROJECT_DIR, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        choices=["all", *STAGES, *OPTIONAL_STAGES],
        default="all",
        help="Pipeline stage to run.",
    )
    parser.add_argument("--sample", action="store_true", help="Use bundled sample data.")
    parser.add_argument("--num-agents", type=int, default=None)
    parser.add_argument("--max-hours", type=int, default=None)
    parser.add_argument("--acs-year", type=int, default=2024)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    selected = STAGES if args.stage == "all" else [args.stage]
    sample_flag = ["--sample"] if args.sample else []
    for stage in selected:
        if stage == "build-panel":
            run_script("build_zone_hour_panel.py", sample_flag)
        elif stage == "census":
            extra = sample_flag[:]
            if not args.sample:
                extra.extend(["--year", str(args.acs_year)])
            run_script("build_acs_zone_features.py", extra)
        elif stage == "identify-events":
            run_script("identify_rain_events.py", [])
        elif stage == "empirical":
            run_script("empirical_analysis.py", [])
        elif stage == "agents":
            extra = sample_flag[:]
            if args.num_agents is not None:
                extra.extend(["--num-agents", str(args.num_agents)])
            run_script("build_agent_population.py", extra)
        elif stage == "configs":
            extra = []
            if args.max_hours is not None:
                extra.extend(["--max-hours", str(args.max_hours)])
            run_script("generate_agentsociety_config.py", extra)
        elif stage == "simulate":
            extra = []
            if args.max_hours is not None:
                extra.extend(["--max-hours", str(args.max_hours)])
            run_script("simulate_policy.py", extra)
        elif stage == "metrics":
            run_script("evaluate_policy.py", [])
        elif stage == "report":
            run_script("generate_report.py", [])
        elif stage == "validate":
            extra = sample_flag[:]
            run_script("validate_pipeline.py", extra)


if __name__ == "__main__":
    main()
