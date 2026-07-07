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

Place raw datasets in `nyc_rain_mobility/data/raw/` and mapping files in `nyc_rain_mobility/config/`, then run:

```bash
python nyc_rain_mobility/run_pipeline.py --stage all
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

