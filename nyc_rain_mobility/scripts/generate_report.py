#!/usr/bin/env python3
"""Generate charts and a Markdown report draft for the NYC rain mobility experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from common import PRESENTATION_DIR, PROCESSED_DIR, TABLES_DIR, write_json


CHART_DIR = PRESENTATION_DIR / "charts"


def _load_optional_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_phase_chart(phase_summary: pd.DataFrame, output: Path) -> None:
    import matplotlib.pyplot as plt

    if phase_summary.empty:
        return
    plot = phase_summary.copy()
    order = ["control", "pre_rain", "during_rain", "post_rain", "other_rain"]
    plot["rain_phase"] = pd.Categorical(plot["rain_phase"], categories=order, ordered=True)
    plot = plot.sort_values("rain_phase")
    modes = ["bike_trip_count", "taxi_pickup_count", "subway_ridership"]
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.8), constrained_layout=True)
    labels = {
        "bike_trip_count": "Citi Bike trips",
        "taxi_pickup_count": "Taxi pickups",
        "subway_ridership": "Subway ridership",
    }
    for ax, mode in zip(axes, modes):
        ax.bar(plot["rain_phase"].astype(str), plot[mode], color="#4c78a8")
        ax.set_title(labels[mode])
        ax.tick_params(axis="x", rotation=30)
        ax.set_ylabel("count")
    fig.suptitle("Observed mobility by rain phase")
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=160)
    plt.close(fig)


def _save_policy_chart(policy_metrics: pd.DataFrame, output: Path) -> None:
    import matplotlib.pyplot as plt

    if policy_metrics.empty:
        return
    plot = policy_metrics.copy()
    plot["scenario_label"] = (
        plot["scenario"]
        .str.replace("experiment_1_", "", regex=False)
        .str.replace("experiment_2_", "", regex=False)
        .str.replace("experiment_3_", "", regex=False)
        .str.replace("experiment_4_", "", regex=False)
        .str.replace("_", " ", regex=False)
    )
    metrics = ["bike_share", "taxi_share", "subway_share", "unmet_demand_share"]
    fig, ax = plt.subplots(figsize=(10, 4.5), constrained_layout=True)
    width = 0.18
    x = range(len(plot))
    colors = ["#4c78a8", "#f58518", "#54a24b", "#e45756"]
    for idx, metric in enumerate(metrics):
        offsets = [v + (idx - 1.5) * width for v in x]
        ax.bar(offsets, plot[metric], width=width, label=metric.replace("_", " "), color=colors[idx])
    ax.set_xticks(list(x))
    ax.set_xticklabels(plot["scenario_label"], rotation=20, ha="right")
    ax.set_ylim(0, max(0.1, min(1.0, float(plot[metrics].max().max()) * 1.25)))
    ax.set_ylabel("share")
    ax.set_title("Policy scenario mode shares and unmet demand")
    ax.legend(ncol=2, fontsize=8)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=160)
    plt.close(fig)


def _save_fairness_chart(fairness: pd.DataFrame, output: Path) -> None:
    import matplotlib.pyplot as plt

    if fairness.empty:
        return
    pivot = fairness.pivot_table(
        index="archetype",
        columns="scenario",
        values="unmet_demand_share",
        aggfunc="mean",
        fill_value=0,
    )
    fig, ax = plt.subplots(figsize=(10, 4.8), constrained_layout=True)
    pivot.plot(kind="bar", ax=ax)
    ax.set_ylabel("unmet demand share")
    ax.set_title("Unmet demand by traveler archetype")
    ax.tick_params(axis="x", rotation=25)
    ax.legend(fontsize=7)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=160)
    plt.close(fig)


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _mode_comparison_lines(summary: dict) -> list[str]:
    comparisons = summary.get("mode_comparisons", {})
    rows = []
    for mode in ["bike", "taxi", "subway"]:
        item = comparisons.get(mode, {})
        if not item:
            continue
        rows.append(
            "| {mode} | {control:.3f} | {during:.3f} | {change:.1f}% |".format(
                mode=mode,
                control=float(item.get("control_mean_per_zone_hour", 0.0)),
                during=float(item.get("during_rain_mean_per_zone_hour", 0.0)),
                change=float(item.get("percent_change", 0.0)),
            )
        )
    return rows


def _policy_table(policy_metrics: pd.DataFrame) -> list[str]:
    if policy_metrics.empty:
        return ["No policy metrics were generated."]
    rows = [
        "| Scenario | Bike | Taxi | Subway | Delay | Cancel | Unmet demand | Rain exposure |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in policy_metrics.sort_values("scenario").itertuples(index=False):
        rows.append(
            "| {scenario} | {bike} | {taxi} | {subway} | {delay} | {cancel} | {unmet} | {exposure} |".format(
                scenario=row.scenario,
                bike=_fmt_pct(float(row.bike_share)),
                taxi=_fmt_pct(float(row.taxi_share)),
                subway=_fmt_pct(float(row.subway_share)),
                delay=_fmt_pct(float(row.delay_share)),
                cancel=_fmt_pct(float(row.cancel_share)),
                unmet=_fmt_pct(float(row.unmet_demand_share)),
                exposure=_fmt_pct(float(row.rain_exposure_share)),
            )
        )
    return rows


def generate_report(output: Path) -> Path:
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    phase_summary = _load_optional_csv(TABLES_DIR / "phase_summary.csv")
    policy_metrics = _load_optional_csv(TABLES_DIR / "policy_metrics.csv")
    fairness = _load_optional_csv(TABLES_DIR / "policy_fairness_by_archetype.csv")
    empirical = _load_json(TABLES_DIR / "empirical_summary.json")
    events = _load_json(PROCESSED_DIR / "rain_events.json")

    phase_chart = CHART_DIR / "observed_mobility_by_phase.png"
    policy_chart = CHART_DIR / "policy_mode_shares.png"
    fairness_chart = CHART_DIR / "unmet_demand_by_archetype.png"
    _save_phase_chart(phase_summary, phase_chart)
    _save_policy_chart(policy_metrics, policy_chart)
    _save_fairness_chart(fairness, fairness_chart)

    event_count = len(events) if isinstance(events, list) else 0
    mode_lines = _mode_comparison_lines(empirical)
    if not mode_lines:
        mode_lines = ["| bike | 0.000 | 0.000 | 0.0% |"]

    markdown = []
    markdown.append("# Rainstorm-Induced Travel Behavior Shifts in New York City")
    markdown.append("")
    markdown.append("## Executive Summary")
    markdown.append("")
    markdown.append(
        "This report draft is generated from the current pipeline outputs. "
        "The bundled sample data is intentionally tiny; after replacing sample inputs with real 2024 NYC data, "
        "rerun the pipeline to refresh all tables and charts."
    )
    markdown.append("")
    markdown.append("## Research Question")
    markdown.append("")
    markdown.append(
        "How do New York City travelers change mode choices before, during, and after rainstorms, "
        "and which policy interventions reduce trip cancellation, delay, and unequal access to alternatives?"
    )
    markdown.append("")
    markdown.append("## Data and Pipeline")
    markdown.append("")
    markdown.append("- Mobility data: Citi Bike trips, NYC TLC taxi trips, and MTA subway hourly ridership.")
    markdown.append("- Weather data: hourly precipitation and weather conditions.")
    markdown.append("- Spatial unit: taxi zone by hour.")
    markdown.append(f"- Detected rainstorm events in current run: `{event_count}`.")
    markdown.append("")
    markdown.append("## Empirical Mobility Shift")
    markdown.append("")
    markdown.append("| Mode | Control mean per zone-hour | During-rain mean per zone-hour | Percent change |")
    markdown.append("|---|---:|---:|---:|")
    markdown.extend(mode_lines)
    markdown.append("")
    if phase_chart.exists():
        markdown.append(f"![Observed mobility by phase](charts/{phase_chart.name})")
        markdown.append("")
    markdown.append("## Policy Simulation")
    markdown.append("")
    markdown.extend(_policy_table(policy_metrics))
    markdown.append("")
    if policy_chart.exists():
        markdown.append(f"![Policy mode shares](charts/{policy_chart.name})")
        markdown.append("")
    markdown.append("## Fairness and Resilience")
    markdown.append("")
    markdown.append(
        "The fairness view compares unmet demand by traveler archetype. In the full-data run, this should be "
        "interpreted together with zone-level subway accessibility, taxi supply, and socioeconomic context."
    )
    markdown.append("")
    if fairness_chart.exists():
        markdown.append(f"![Unmet demand by archetype](charts/{fairness_chart.name})")
        markdown.append("")
    markdown.append("## Next Evidence Needed")
    markdown.append("")
    markdown.append("- Run the same pipeline on one real pilot month, preferably July 2024.")
    markdown.append("- Compare detected rainstorm events against weather records or local weather reports.")
    markdown.append("- Recalibrate rain sensitivity and substitution parameters from real empirical shifts.")
    markdown.append("- Run AgentSociety2 scenarios with LLM-backed PersonAgent decisions after the deterministic baseline is stable.")
    markdown.append("")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(markdown), encoding="utf-8")
    write_json(
        TABLES_DIR / "report_manifest.json",
        {
            "report": str(output),
            "charts": [str(phase_chart), str(policy_chart), str(fairness_chart)],
            "rain_event_count": event_count,
        },
    )
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PRESENTATION_DIR / "report.md")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = generate_report(args.output)
    print(f"Wrote report draft to {report}")


if __name__ == "__main__":
    main()

