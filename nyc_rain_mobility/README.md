# NYC Rain Mobility Pipeline

This project studies how rainstorms change travel decisions in New York City before, during, and after storm events. The pipeline turns public mobility and weather data into an empirical baseline, calibrates traveler archetypes, generates AgentSociety2 experiment configs, and runs policy simulations.

## Research Scope

- City: New York City.
- Modes: Citi Bike, yellow/green taxi or HVFHV, and subway.
- Unit: taxi zone by hour.
- Event window: 24 hours before rainstorm, rainstorm hours, and 24 hours after rainstorm.
- First implementation target: 2024 summer months, then 5-10 storm events.

## Pipeline Stages

1. `build-panel`: aggregate raw mobility and weather data to `zone_id x hour`.
2. `identify-events`: label pre-rain, during-rain, post-rain, and control hours.
3. `empirical`: compute observed mode shifts and spatial impacts.
4. `agents`: synthesize traveler archetypes from empirical patterns and zone context.
5. `configs`: generate AgentSociety2 `init_config.json` and `steps.yaml` for policy scenarios.
6. `simulate`: run a deterministic policy simulator for fast validation without LLM calls.
7. `metrics`: evaluate scenario outcomes and policy tradeoffs.

## Quick Dry Run

The sample data is tiny and only proves the pipeline works end to end.

```bash
python nyc_rain_mobility/run_pipeline.py --sample --stage all
```

If you want to run inside the AgentSociety2 `uv` environment:

```bash
cd agentsociety
uv sync
uv run python ../nyc_rain_mobility/run_pipeline.py --sample --stage all
```

## Real Data Run

Put raw files under `nyc_rain_mobility/data/raw/` using the names documented in `data_description.md`, then run:

```bash
python nyc_rain_mobility/run_pipeline.py --stage all
```

The default output locations are:

- `data/processed/panel_zone_hour.csv`
- `data/processed/panel_labeled.csv`
- `data/processed/rain_events.json`
- `presentation/tables/empirical_summary.json`
- `config/agent_population.json`
- `hypothesis_1/experiment_*/init/init_config.json`
- `hypothesis_1/experiment_*/init/steps.yaml`
- `hypothesis_1/experiment_*/run/simulated_decisions.csv`
- `presentation/tables/policy_metrics.csv`

## AgentSociety2 Integration

Generated configs use a custom environment module:

```text
nyc_rain_mobility/custom/envs/rain_mobility_env.py
```

Run an AgentSociety2 scenario after setting LLM credentials:

```bash
cd agentsociety
uv run python -m agentsociety2.society.cli \
  --config ../nyc_rain_mobility/hypothesis_1/experiment_1_baseline/init/init_config.json \
  --steps ../nyc_rain_mobility/hypothesis_1/experiment_1_baseline/init/steps.yaml \
  --run-dir ../nyc_rain_mobility/hypothesis_1/experiment_1_baseline/run \
  --experiment-id nyc_rain_baseline \
  --log-file ../nyc_rain_mobility/hypothesis_1/experiment_1_baseline/run/output.log
```

