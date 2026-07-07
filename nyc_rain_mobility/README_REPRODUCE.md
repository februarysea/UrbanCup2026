# Reproduction Notes

## 1. Environment

The scripts require Python 3.11+ and `pandas`. The easiest path is to use the local AgentSociety2 environment:

```bash
cd agentsociety
uv sync
```

## 2. Dry Run

From the repository root:

```bash
python nyc_rain_mobility/run_pipeline.py --sample --stage all
```

Or from the AgentSociety2 environment:

```bash
cd agentsociety
uv run python ../nyc_rain_mobility/run_pipeline.py --sample --stage all
```

## 3. Full Data Run

Inspect real data URLs and expected file sizes:

```bash
python nyc_rain_mobility/scripts/download_real_data.py \
  --year 2024 --months 7
```

Download one pilot month:

```bash
python nyc_rain_mobility/scripts/download_real_data.py \
  --year 2024 --months 7 \
  --datasets citibike yellow green mta weather zones \
  --execute
```

Generate mapping files:

```bash
python nyc_rain_mobility/scripts/generate_zone_maps.py
```

Then run:

```bash
python nyc_rain_mobility/run_pipeline.py --stage all
```

The report draft is written to:

```text
nyc_rain_mobility/presentation/report.md
```

Validate inputs and generated outputs:

```bash
AGENTSOCIETY_LLM_API_KEY=test-key \
python nyc_rain_mobility/scripts/validate_pipeline.py --sample --check all
```

Create a lightweight submission bundle:

```bash
python nyc_rain_mobility/scripts/package_submission.py \
  --competition event3 \
  --team-name team_name \
  --work-name nyc_rain_mobility \
  --zip
```

Validate the AgentSociety2 custom environment discovery path:

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

## 4. AgentSociety2 Scenario Run

After config generation, run a scenario with:

```bash
cd agentsociety
uv run python -m agentsociety2.society.cli \
  --config ../nyc_rain_mobility/hypothesis_1/experiment_1_baseline/init/init_config.json \
  --steps ../nyc_rain_mobility/hypothesis_1/experiment_1_baseline/init/steps.yaml \
  --run-dir ../nyc_rain_mobility/hypothesis_1/experiment_1_baseline/run \
  --experiment-id nyc_rain_baseline \
  --log-file ../nyc_rain_mobility/hypothesis_1/experiment_1_baseline/run/output.log
```

LLM credentials are required for the AgentSociety2 CLI. The deterministic simulator does not require LLM credentials.
