# UrbanCup2026

Urban Cup 2026 competition workspace.

Current experiment:

- `nyc_rain_mobility/`: rainstorm-induced travel behavior shifts in New York City, using Citi Bike, NYC TLC taxi, MTA subway ridership, and hourly rainfall data.

The `agentsociety/` directory is treated as a local framework dependency and is not committed in this root competition repository.

Useful entrypoints:

- `python nyc_rain_mobility/run_pipeline.py --sample --stage all`
- `python nyc_rain_mobility/scripts/package_submission.py --zip`
