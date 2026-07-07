# Rainstorm-Induced Travel Behavior Shifts in New York City

## Executive Summary

This report draft is generated from the current pipeline outputs. The bundled sample data is intentionally tiny; after replacing sample inputs with real 2024 NYC data, rerun the pipeline to refresh all tables and charts.

## Research Question

How do New York City travelers change mode choices before, during, and after rainstorms, and which policy interventions reduce trip cancellation, delay, and unequal access to alternatives?

## Data and Pipeline

- Mobility data: Citi Bike trips, NYC TLC taxi trips, and MTA subway hourly ridership.
- Weather data: hourly precipitation and weather conditions.
- Spatial unit: taxi zone by hour.
- Detected rainstorm events in current run: `1`.

## Empirical Mobility Shift

| Mode | Control mean per zone-hour | During-rain mean per zone-hour | Percent change |
|---|---:|---:|---:|
| bike | 0.167 | 0.111 | -33.3% |
| taxi | 0.167 | 0.333 | 100.0% |
| subway | 200.000 | 438.889 | 119.4% |

![Observed mobility by phase](charts/observed_mobility_by_phase.png)

## Policy Simulation

| Scenario | Bike | Taxi | Subway | Delay | Cancel | Unmet demand | Rain exposure |
|---|---:|---:|---:|---:|---:|---:|---:|
| experiment_1_baseline | 21.5% | 22.2% | 48.6% | 5.6% | 2.1% | 7.6% | 2.8% |
| experiment_2_early_warning | 23.6% | 25.7% | 40.3% | 6.9% | 3.5% | 10.4% | 2.8% |
| experiment_3_transit_guidance | 19.4% | 27.8% | 47.2% | 4.9% | 0.7% | 5.6% | 0.7% |
| experiment_4_taxi_support | 18.8% | 27.8% | 46.5% | 6.2% | 0.7% | 6.9% | 0.0% |

![Policy mode shares](charts/policy_mode_shares.png)

## Fairness and Resilience

The fairness view compares unmet demand by traveler archetype. In the full-data run, this should be interpreted together with zone-level subway accessibility, taxi supply, and socioeconomic context.

![Unmet demand by archetype](charts/unmet_demand_by_archetype.png)

## Next Evidence Needed

- Run the same pipeline on one real pilot month, preferably July 2024.
- Compare detected rainstorm events against weather records or local weather reports.
- Recalibrate rain sensitivity and substitution parameters from real empirical shifts.
- Run AgentSociety2 scenarios with LLM-backed PersonAgent decisions after the deterministic baseline is stable.
