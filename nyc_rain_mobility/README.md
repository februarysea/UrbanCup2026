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
8. `report`: generate charts and a Markdown report draft.
9. `validate`: check required inputs, generated outputs, and AgentSociety2 custom-module wiring.

## Quick Dry Run

The sample data is tiny and only proves the pipeline works end to end.

```bash
python nyc_rain_mobility/run_pipeline.py --sample --stage all
AGENTSOCIETY_LLM_API_KEY=test-key \
python nyc_rain_mobility/run_pipeline.py --sample --stage validate
```

If you want to run inside the AgentSociety2 `uv` environment:

```bash
cd agentsociety
uv sync
uv run python ../nyc_rain_mobility/run_pipeline.py --sample --stage all
AGENTSOCIETY_LLM_API_KEY=test-key \
uv run python ../nyc_rain_mobility/run_pipeline.py --sample --stage validate
```

## Real Data Run

First inspect the public download plan:

```bash
python nyc_rain_mobility/scripts/download_real_data.py \
  --year 2024 --months 6 7 8 9
```

Then download selected datasets. Citi Bike files are very large, so start with one month:

```bash
python nyc_rain_mobility/scripts/download_real_data.py \
  --year 2024 --months 7 \
  --datasets citibike yellow green mta weather zones \
  --execute
```

Generate station-to-zone maps from station coordinates and NYC taxi zone GeoJSON:

```bash
python nyc_rain_mobility/scripts/generate_zone_maps.py
```

Then run the full pipeline:

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
- `presentation/charts/*.png`
- `presentation/report.md`
- `presentation/tables/validation_summary.json`
- `submission_bundle/<submission_name>_<timestamp>/`

## Real Data Utilities

- `scripts/download_real_data.py`: lists or downloads Citi Bike, TLC taxi, MTA subway, weather, and taxi zone GeoJSON inputs.
- `scripts/generate_zone_maps.py`: spatially joins Citi Bike and MTA station coordinates to taxi zones using `shapely`.
- `scripts/build_zone_hour_panel.py`: chunk-reads large Citi Bike CSV/ZIP files to avoid loading full monthly files at once.
- `scripts/generate_report.py`: creates report charts and `presentation/report.md` from current pipeline outputs.
- `scripts/validate_pipeline.py`: checks data schemas, required outputs, generated configs, charts, report files, and AgentSociety2 custom-module wiring.
- `scripts/package_submission.py`: creates a lightweight Urban Cup bundle with report, workspace code, sample data, init configs, charts, tables, and manifest.

## Submission Bundle

After running and validating the pipeline, create an upload-ready bundle:

```bash
AGENTSOCIETY_LLM_API_KEY=test-key \
python nyc_rain_mobility/run_pipeline.py --sample --stage validate
python nyc_rain_mobility/scripts/package_submission.py \
  --competition event3 \
  --team-name team_name \
  --work-name nyc_rain_mobility \
  --zip
```

The bundle excludes raw public mobility files by default because they are large and reproducible through `download_real_data.py`.

## AgentSociety2 Integration

Generated configs use a workspace-level custom environment module so AgentSociety2's default scanner can discover it:

```text
custom/envs/rain_mobility_env.py
```

The project-level path `nyc_rain_mobility/custom/envs/rain_mobility_env.py` remains as a compatibility import.

Validate the custom environment with AgentSociety2's local validator:

```bash
cd agentsociety
AGENTSOCIETY_LLM_API_KEY=test-key \
PYTHONPATH=packages/agentsociety2:.. \
uv run python extension/skills/agentsociety-create-env-module/v1.0.0/scripts/validate.py \
  --workspace .. \
  --file custom/envs/rain_mobility_env.py \
  --class-name RainMobilityEnv \
  --json
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
