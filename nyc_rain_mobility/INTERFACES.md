# Data Interfaces

This file fixes the handoff contracts between the mobility, weather, Census,
agent-generation, and reporting tasks. All join keys should stay stable.

## Common Keys

- Spatial unit: TLC taxi zone `zone_id` / `LocationID`.
- Time unit: hourly timestamp in New York local time.
- Main panel key: `zone_id, hour`.

## Mobility Panel From Xinyue

Expected output before weather merge:

```text
zone_id
hour
bike_trip_count
taxi_pickup_count
taxi_dropoff_count optional
subway_ridership
bus_ridership optional
```

Current script: `scripts/build_zone_hour_panel.py`.

Bus is optional because MTA bus ridership is route-hour, not zone-hour. If used,
provide a route-to-zone allocation file:

```text
bus_route
zone_id
allocation_weight
```

## Weather Panel From Xinxi

Expected output:

```text
zone_id
hour
precipitation
rain
temperature_2m
wind_speed_10m
rain_phase
event_id optional
```

Required rain phases:

```text
control
pre_rain
during_rain
post_rain
other_rain
```

Current scripts:

- `scripts/build_zone_hour_panel.py`
- `scripts/identify_rain_events.py`

## Census Zone Features From Chunhou

Output path:

```text
config/acs_zone_features.csv
```

Builder:

```bash
cd agentsociety
uv run python ../nyc_rain_mobility/scripts/build_acs_zone_features.py
```

Official run prerequisites:

```bash
cd agentsociety
uv run python ../nyc_rain_mobility/scripts/download_real_data.py --datasets zones --execute
uv run python ../nyc_rain_mobility/scripts/build_acs_zone_features.py --year 2024
```

Offline schema check:

```bash
cd agentsociety
uv run python ../nyc_rain_mobility/scripts/build_acs_zone_features.py \
  --sample \
  --output ../nyc_rain_mobility/data/interim/acs_zone_features_sample_generated.csv
```

Output schema:

```text
zone_id
borough
zone_name
total_population
worker_population
household_count
median_household_income
no_vehicle_share
transit_commute_share
bike_commute_share
walk_commute_share
taxi_commute_share
work_from_home_share
poverty_share
low_income_share
avg_commute_time
acs_year
interpolation_method
acs_source
```

Method:

- Download ACS 5-year tract variables for the five NYC counties.
- Download Census tract geometries from TIGERweb.
- Reproject tracts and taxi zones to EPSG:2263.
- Area-weight tract count variables to TLC taxi zones.
- Compute taxi-zone shares after allocation.
- Approximate median household income by household-weighted tract medians.

## Agent Population From Chunhou

Output path:

```text
config/agent_population.json
```

Main fields:

```text
id
archetype
home_zone
origin_zone
work_zone
destination_zone
income_group
preferred_mode
rain_sensitivity
subway_accessibility
bus_accessibility
taxi_availability
cost_sensitivity
schedule_flexibility
commute_rigidity
alternative_access
transit_dependency
vehicle_access
walk_tolerance
```

Archetypes are behavioral labels derived from these attributes, not observed
Census labels.

## Simulation Outputs From Chunhou

Decision logs:

```text
hypothesis_1/experiment_*/run/simulated_decisions.csv
```

Expected fields:

```text
scenario
policy
agent_id
archetype
home_zone
origin_zone
destination_zone
hour
rain_phase
event_id
precipitation
decision
chosen_mode
rain_exposure
unmet_demand
```

Decision set:

```text
bike
subway
bus
taxi
walk
delay
cancel
```

Summary metrics:

```text
presentation/tables/policy_metrics.csv
presentation/tables/policy_fairness_by_archetype.csv
```

These files are the input for final reporting and policy comparison.
