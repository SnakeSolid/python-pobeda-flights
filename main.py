#!/usr/bin/env python3
"""
Script for parsing data on direct flights of the airline "Pobeda"
with results saved to SQLite.

Performs sequential requests for each date in the given range.
Between requests – random delay from 30 to 60 seconds.
Data is saved to an SQLite database with deduplication by the current date.
A continuous mode is supported for periodic data collection every 8 hours.
Use --force to refresh data even if a recent record already exists.
"""

import argparse
import datetime
import json
import logging
import random
import sqlite3
import sys
import time
from enum import Enum
from typing import Any, Dict, List, Optional

import requests


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Parse Pobeda direct flights (OGZ -> LED) with SQLite storage."
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default="29.07.2026",
        help="Start date for flights in DD.MM.YYYY format (default: 29.07.2026)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default="12.08.2026",
        help="End date for flights in DD.MM.YYYY format (default: 12.08.2026)",
    )
    parser.add_argument(
        "--origin",
        type=str,
        default="OGZ",
        help="Origin city code (default: OGZ)",
    )
    parser.add_argument(
        "--destination",
        type=str,
        default="LED",
        help="Destination city code (default: LED)",
    )
    parser.add_argument(
        "--delay-min",
        type=float,
        default=30.0,
        help="Minimum delay between requests in seconds (default: 30)",
    )
    parser.add_argument(
        "--delay-max",
        type=float,
        default=60.0,
        help="Maximum delay between requests in seconds (default: 60)",
    )
    parser.add_argument(
        "--db",
        type=str,
        default="flights.db",
        help="Path to SQLite database file (default: flights.db)",
    )
    parser.add_argument(
        "--dump",
        action="store_true",
        help="Dump all data from DB to CSV and exit (no parsing)",
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Infinite mode: after processing all dates, wait 8 hours and repeat",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force API requests even if a recent record already exists in the database",
    )
    return parser.parse_args()


def init_db(db_path: str):
    """Create the price storage table if it does not exist."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_date TEXT NOT NULL,        -- date of the query (YYYY.MM.DD)
            flight_date TEXT NOT NULL,       -- date of the flight (YYYY.MM.DD)
            min_price REAL NOT NULL,         -- minimum price
            origin TEXT NOT NULL,            -- origin city code
            destination TEXT NOT NULL,       -- destination city code
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(query_date, flight_date, origin, destination)
        )
    """)
    conn.commit()
    conn.close()


def save_price(
    db_path: str,
    query_date: str,
    flight_date: str,
    min_price: float,
    origin: str,
    destination: str,
):
    """Save the price to the database (ignoring duplicates)."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT OR REPLACE INTO prices (query_date, flight_date, min_price, origin, destination)
            VALUES (?, ?, ?, ?, ?)
        """,
            (query_date, flight_date, min_price, origin, destination),
        )
        conn.commit()
    except sqlite3.Error as e:
        logging.error(f"Error saving to database: {e}")
    finally:
        conn.close()


def record_exists(
    db_path: str,
    query_date: str,
    flight_date: str,
    origin: str,
    destination: str,
) -> bool:
    """
    Check if a record already exists that was created within the last max_age_hours.
    Returns True if a fresh record exists, False otherwise.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT 1 FROM prices
        WHERE query_date = ? AND flight_date = ? AND origin = ? AND destination = ?
        LIMIT 1
    """,
        (query_date, flight_date, origin, destination),
    )
    exists = cursor.fetchone() is not None
    conn.close()
    return exists


def dump_database(db_path: str):
    """
    Dump all database data to stdout in CSV format.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT query_date, flight_date, min_price, origin, destination, created_at
        FROM prices
        ORDER BY query_date DESC, flight_date ASC
    """)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print("No data in database.")
        return

    # CSV headers
    print("query_date;flight_date;min_price;origin;destination;created_at")
    for row in rows:
        print(";".join(str(col) for col in row))


def generate_unique_tab_id() -> str:
    """Generate a random Unique-Tab-Id similar to the one used in browsers."""
    timestamp = str(int(time.time() * 1000))
    random_part = "".join(
        random.choices(
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=20
        )
    )
    return timestamp + random_part


def get_referer_url() -> str:
    """Build the Referer URL for the API request (mirrors the working curl)."""
    return "https://ticket.flypobeda.ru/websky/"


def fetch_flights_for_date(
    session: requests.Session,
    date_str: str,
    origin: str,
    destination: str,
    unique_tab_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Send a request to the API for the specified date and return the JSON response.
    Returns None on error.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:151.0) Gecko/20100101 Firefox/151.0",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
        "Origin": "https://ticket.flypobeda.ru",
        "Referer": get_referer_url(),
        "Unique-Tab-Id": unique_tab_id,
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
    }

    data = {
        "searchGroupId": "standard",
        "segmentsCount": 1,
        "date[0]": date_str,
        "origin-city-code[0]": origin,
        "destination-city-code[0]": destination,
        "destination-port-code[0]": destination,
        "adultsCount": 1,
        "youngAdultsCount": 0,
        "childrenCount": 0,
        "infantsWithSeatCount": 0,
        "infantsWithoutSeatCount": 0,
    }

    url = "https://ticket.flypobeda.ru/websky/json/search-variants-mono-brand-cartesian"

    try:
        response = session.post(url, headers=headers, data=data, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Request error for date {date_str}: {e}")
        return None
    except json.JSONDecodeError as e:
        logging.error(f"JSON parse error for date {date_str}: {e}")
        return None


def extract_direct_flights(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract information about direct flights (no connections) from the API response.
    Returns a list of flight objects where connections == [].
    """
    flights = data.get("flights", [])
    direct_flights = []
    for flight in flights:
        connections = flight.get("connections", None)
        if connections is not None and len(connections) == 0:
            direct_flights.append(flight)
    return direct_flights


def get_min_price_for_chain(
    prices_obj: List[Dict[str, Any]], chain_id: str
) -> Optional[float]:
    """
    For the given chain_id, find the minimum price among all available fares.
    Returns a float or None if no price is found.
    """
    if not isinstance(prices_obj, list):
        logging.warning(f"prices has unexpected type: {type(prices_obj)}")
        return None

    for price_map in prices_obj:
        chain_prices = price_map.get(chain_id)
        if not chain_prices:
            continue

        min_price = None
        for item in chain_prices:
            price_str = item.get("price")
            if price_str is not None:
                try:
                    price = float(price_str)
                    if min_price is None or price < min_price:
                        min_price = price
                except ValueError:
                    logging.warning(
                        f"Failed to convert price '{price_str}' to a number"
                    )
                    continue
        if min_price is not None:
            return min_price

    return None


def convert_date_format(date_ddmmyyyy: str) -> str:
    """Convert date from DD.MM.YYYY format to YYYY.MM.DD."""
    try:
        day, month, year = date_ddmmyyyy.split(".")
        return f"{year}.{month}.{day}"
    except ValueError:
        logging.warning(f"Invalid date format: {date_ddmmyyyy}")
        return date_ddmmyyyy


def date_range(start_str: str, end_str: str):
    """Generator yielding dates in DD.MM.YYYY format from start to end inclusive."""
    try:
        start = datetime.datetime.strptime(start_str, "%d.%m.%Y").date()
        end = datetime.datetime.strptime(end_str, "%d.%m.%Y").date()
    except ValueError as e:
        logging.error(f"Error parsing dates: {e}")
        sys.exit(1)

    if start > end:
        logging.error("Start date is after end date")
        sys.exit(1)

    current = start
    while current <= end:
        yield current.strftime("%d.%m.%Y")
        current += datetime.timedelta(days=1)


class ProcessResult(Enum):
    """Result of processing a single flight date."""

    SAVED = "saved"
    FAILED = "failed"
    SKIPPED = "skipped"


def process_date(
    session: requests.Session,
    db_path: str,
    date_str: str,
    origin: str,
    destination: str,
    query_date_obj: datetime.date,
    idx: int,
    total: int,
    unique_tab_id: str,
    force: bool = False,
) -> ProcessResult:
    """
    Process a single date: check for an existing record, make a request if needed,
    save the result.

    Returns:
        ProcessResult.SAVED   — new data was saved (API request was made)
        ProcessResult.FAILED  — API request was made but failed or returned no data
        ProcessResult.SKIPPED — skipped because a fresh record already exists (no API request was made)
    """
    flight_date_formatted = convert_date_format(date_str)
    query_date_str = query_date_obj.strftime("%Y.%m.%d")

    # Skip request if a fresh record already exists and force is not set
    if not force and record_exists(
        db_path, query_date_str, flight_date_formatted, origin, destination
    ):
        logging.info(f"Flight date {date_str}: fresh record exists, skipping request")
        return ProcessResult.SKIPPED

    logging.info(f"Processing date {date_str} ({idx}/{total}) – requesting API")

    data = fetch_flights_for_date(session, date_str, origin, destination, unique_tab_id)
    if data is None:
        logging.warning(f"Date {date_str} skipped due to error")
        return ProcessResult.FAILED

    if data.get("result") != "ok":
        logging.warning(
            f"API returned result != ok for date {date_str}: {data.get('result')}"
        )
        return ProcessResult.FAILED

    direct_flights = extract_direct_flights(data)
    prices = data.get("prices")
    if not prices:
        logging.warning(f"No price data for date {date_str}")
        return ProcessResult.FAILED

    saved_any = False
    for flight in direct_flights:
        chain_id = flight.get("chainId")
        if not chain_id:
            continue

        flight_segments = flight.get("flights", [])
        if not flight_segments:
            continue
        depart_date = flight_segments[0].get("departuredate")
        if not depart_date:
            continue

        min_price = get_min_price_for_chain(prices, chain_id)
        if min_price is None:
            continue

        # Treat prices <= 1 as API error response and skip them
        if min_price <= 1:
            logging.warning(
                f"Suspicious price {min_price:.2f} for chain {chain_id} "
                f"on {depart_date} – treating as error and ignoring"
            )
            continue

        flight_date_formatted = convert_date_format(depart_date)
        save_price(
            db_path,
            query_date_str,
            flight_date_formatted,
            min_price,
            origin,
            destination,
        )
        logging.info(
            f"Saved: {query_date_str} | {flight_date_formatted} | {min_price:.2f}"
        )
        saved_any = True

    if not saved_any:
        logging.info(f"No direct flights with prices found for date {date_str}")

    return ProcessResult.SAVED if saved_any else ProcessResult.FAILED


def run_parsing_cycle(args) -> None:
    """
    Execute one full pass through all dates (from start_date to end_date).
    """
    session = requests.Session()
    unique_tab_id = generate_unique_tab_id()
    try:
        session.get("https://ticket.flypobeda.ru/websky/", timeout=30)
        logging.info("Session initialized")
    except requests.exceptions.RequestException as e:
        logging.warning(f"Failed to initialize session: {e}")

    dates = list(date_range(args.start_date, args.end_date))
    total = len(dates)
    query_date_obj = datetime.date.today()

    for idx, date_str in enumerate(dates):
        result = process_date(
            session,
            args.db,
            date_str,
            args.origin,
            args.destination,
            query_date_obj,
            idx + 1,
            total,
            unique_tab_id,
            force=args.force,
        )

        # Delay before the next request (except for the last one),
        # only if an actual API request was made
        if result is not ProcessResult.SKIPPED and idx < total - 1:
            delay = random.uniform(args.delay_min, args.delay_max)
            logging.info(f"Waiting {delay:.1f} seconds...")
            time.sleep(delay)


CYCLE_INTERVAL_HOURS = 8


def seconds_until_next_cycle() -> float:
    """Return the number of seconds until the next data collection cycle (8 hours)."""
    return CYCLE_INTERVAL_HOURS * 3600


def main():
    args = parse_arguments()

    # Configure logging to stderr
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        stream=sys.stderr,
    )

    # Initialize the database
    init_db(args.db)
    logging.info(f"Database: {args.db}")

    # Dump mode
    if args.dump:
        dump_database(args.db)
        return

    if args.continuous:
        logging.info(
            "Starting in continuous mode "
            f"(next cycle every {CYCLE_INTERVAL_HOURS} hours)"
        )
        try:
            while True:
                logging.info("Starting a new data collection cycle")
                run_parsing_cycle(args)
                sleep_seconds = seconds_until_next_cycle()
                logging.info(
                    f"Cycle complete. "
                    f"Next collection in {sleep_seconds:.0f} seconds "
                    f"({sleep_seconds / 3600:.1f} hours)."
                )
                time.sleep(sleep_seconds)
        except KeyboardInterrupt:
            logging.info("Continuous mode stopped by user")
    else:
        logging.info("Starting in single-run mode")
        try:
            run_parsing_cycle(args)
        except KeyboardInterrupt:
            logging.info("Interrupted by user")
        else:
            logging.info("Work finished")


if __name__ == "__main__":
    main()
