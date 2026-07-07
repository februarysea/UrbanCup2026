# Data Description

## Required Datasets

### Citi Bike Trip Data

Source: https://citibikenyc.com/system-data

Used for bike trip counts, user type, station origin/destination, and hour-level storm response.

Expected fields:

- `started_at`
- `ended_at`
- `start_station_id`
- `end_station_id`
- `start_lat`
- `start_lng`
- `end_lat`
- `end_lng`
- `member_casual`
- `rideable_type`

### NYC TLC Trip Record Data

Source: https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page

Used for taxi pickup/dropoff counts and taxi substitution demand.

Expected fields:

- `tpep_pickup_datetime` or `lpep_pickup_datetime` or `pickup_datetime`
- `tpep_dropoff_datetime` or `lpep_dropoff_datetime` or `dropoff_datetime`
- `PULocationID`
- `DOLocationID`
- `trip_distance`
- `total_amount`

### MTA Subway Hourly Ridership

Source: https://data.ny.gov/Transportation/MTA-Subway-Hourly-Ridership-2020-2024/wujg-7c2s

Used for subway station ridership and subway substitution pressure.

Expected fields:

- `transit_timestamp`
- `station_complex_id`
- `station_complex`
- `borough`
- `ridership`

### Weather Data

Preferred source: https://open-meteo.com/en/docs/historical-weather-api

Official alternative: https://www.ncei.noaa.gov/cdo-web/

Expected fields:

- `time`
- `precipitation`
- `rain`
- `temperature_2m`
- `wind_speed_10m`

### Spatial Mapping Files

The pipeline uses taxi zone as the common spatial unit.

Required mapping files:

- `station_zone_map_bike.csv`: `station_id,zone_id`
- `station_zone_map_mta.csv`: `station_complex_id,zone_id`

These can be produced by spatially joining station coordinates to the TLC taxi zone shapefile. For the first version, manually verified mapping files are acceptable.

Implemented helper:

```bash
python nyc_rain_mobility/scripts/download_real_data.py \
  --datasets zones --execute
python nyc_rain_mobility/scripts/generate_zone_maps.py
```

The helper uses the NYC Open Data taxi zone GeoJSON (`8meu-9t5y`) and `shapely` point-in-polygon matching. Citi Bike station coordinates are extracted from trip files; MTA station coordinates are read from the MTA hourly ridership API output.

## Download Helper

The real data downloader is intentionally dry-run by default:

```bash
python nyc_rain_mobility/scripts/download_real_data.py --year 2024 --months 6 7 8 9
```

Use `--execute` only after checking file sizes:

```bash
python nyc_rain_mobility/scripts/download_real_data.py \
  --year 2024 --months 7 \
  --datasets citibike yellow green mta weather zones \
  --execute
```

Notes:

- Citi Bike monthly NYC files can approach or exceed 1 GiB each.
- TLC yellow/green monthly parquet files are smaller and are downloaded from the official TLC CloudFront host.
- MTA data is downloaded with a server-side Socrata aggregation query to reduce duplicate fare-category rows.
- Weather is downloaded from Open-Meteo Archive API and converted to CSV.

### Optional Social Context

ACS and LODES data can be used to calibrate socioeconomic and commute constraints.

Sources:

- ACS: https://www.census.gov/programs-surveys/acs/data.html
- LODES: https://lehd.ces.census.gov/data/

Expected optional file:

- `acs_zone_features.csv`

Expected fields:

- `zone_id`
- `median_household_income`
- `no_vehicle_share`
- `transit_commute_share`
- `low_income_share`
