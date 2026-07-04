# Pobeda Flights

A Python script for collecting data on direct flights of the airline Pobeda with results saved to an SQLite database.

## Description

This tool performs sequential HTTP requests to the Pobeda ticket API for each date in a given range. Between requests, a random delay is applied to avoid excessive load. Data is saved to an SQLite database with deduplication by the current query date. The tool supports both single-run and continuous (every 8 hours) collection modes. Use `--force` to re-fetch data even if a recent record already exists.

By default, the script collects prices for direct flights from Vladikavkaz (OGZ) to Saint Petersburg (LED).

## Requirements

- Python 3.12 or newer
- `uv` package manager

## Installation

Clone the repository and install dependencies:

```
uv sync
```

## Usage

### Basic run

Process the default date range and save results to the SQLite database:

```
uv run main.py
```

### Custom date range and route

```
uv run main.py --start-date 01.08.2026 --end-date 15.08.2026 --origin OGZ --destination LED
```

### Continuous mode

Run in infinite loop mode. After processing all dates in the range, the script waits 8 hours and repeats the cycle:

```
uv run main.py --continuous
```

### Dump database to CSV

Export all collected data from the database to stdout in CSV format:

```
uv run main.py --dump
```

The output format is semicolon-separated with the following columns:

- `query_date`
- `flight_date`
- `min_price`
- `origin`
- `destination`
- `created_at`

### All options

| Argument | Description | Default |
|---|---|---|
| `--start-date` | Start date for flights in DD.MM.YYYY format | `29.07.2026` |
| `--end-date` | End date for flights in DD.MM.YYYY format | `12.08.2026` |
| `--origin` | Origin city code | `OGZ` |
| `--destination` | Destination city code | `LED` |
| `--delay-min` | Minimum delay between requests in seconds | `30` |
| `--delay-max` | Maximum delay between requests in seconds | `60` |
| `--db` | Path to SQLite database file | `flights.db` |
| `--dump` | Dump all data from database to CSV and exit | `false` |
| `--continuous` | Enable infinite collection mode (repeats every 8 hours) | `false` |
| `--force` | Force API requests even if a recent record already exists | `false` |

## Database

The script creates a `prices` table with the following schema:

- `id` – auto-increment primary key
- `query_date` – date of the query (YYYY.MM.DD)
- `flight_date` – date of the flight (YYYY.MM.DD)
- `min_price` – minimum price found
- `origin` – origin city code
- `destination` – destination city code
- `created_at` – timestamp of record creation

A unique constraint on `(query_date, flight_date, origin, destination)` prevents duplicate entries for the same query date.

## Logging

All log messages are written to stderr. The database dump output is written to stdout, allowing log and data streams to be separated.

## Project structure

```
pobeda-flights/
├── main.py          # Main script
├── pyproject.toml   # Project configuration and dependencies
├── uv.lock          # Lock file for dependencies
├── flights.db       # SQLite database (created on first run)
└── README.md        # This file
```

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
