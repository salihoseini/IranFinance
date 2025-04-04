import requests
import schedule
import time
import sqlite3
import logging
import os
from datetime import datetime

# --- Configuration ---
API_URL = "http://et.tala.ir/webservice/rafshan/6397db883000095bb8ed65398865c994"
DB_FILE = "prices.db"
LOG_FILE = "price_miner.log"
FETCH_INTERVAL_MINUTES = 1

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler() # Also print to console
    ])

# --- Database Setup ---
def setup_database():
    """Creates the database and prices table if they don't exist."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            # Prices table: Stores the latest processed price for each item
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                caption TEXT PRIMARY KEY,
                value REAL NOT NULL,
                timestamp INTEGER NOT NULL
            )
            """)
            conn.commit()
            logging.info("Database setup complete.")
    except sqlite3.Error as e:
        logging.error(f"Database setup error: {e}")
        raise # Reraise to stop the script if DB setup fails

# --- Price Fetching and Processing ---
def fetch_prices():
    """Fetches raw price data from the API."""
    try:
        response = requests.get(API_URL, timeout=10) # Add timeout
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching API data: {e}")
        return None

def process_prices(api_data):
    """Processes raw data, applies multipliers, and returns final values."""
    if not api_data:
        return {}

    processed = {}
    for key, item_data in api_data.items():
        try:
            if item_data and 'caption' in item_data and 'value' in item_data:
                caption = item_data['caption']
                raw_value = float(item_data['value'])

                if caption is None or not isinstance(caption, str) or caption.strip() == "":
                    logging.warning(f"Skipping item with invalid caption: {item_data}")
                    continue

                # Apply conditional multipliers
                if "انس" in caption:  # Check for "ounce"
                    processed_value = raw_value * 10
                else:
                    processed_value = raw_value * 0.1

                processed[caption] = processed_value
            else:
                 logging.warning(f"Skipping invalid item data: Key='{key}', Data='{item_data}'")

        except (ValueError, TypeError) as e:
            logging.warning(f"Could not process item: Key='{key}', Data='{item_data}'. Error: {e}")
            continue # Skip this item if value conversion fails

    return processed

# --- Database Storage ---
def store_prices(processed_prices):
    """Stores processed prices into the SQLite database."""
    if not processed_prices:
        logging.info("No processed prices to store.")
        return

    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            timestamp = int(datetime.now().timestamp()) # Use Unix timestamp

            for caption, value in processed_prices.items():
                # Use INSERT OR REPLACE to add new or update existing prices
                cursor.execute("""
                INSERT OR REPLACE INTO prices (caption, value, timestamp)
                VALUES (?, ?, ?)
                """, (caption, value, timestamp))

            conn.commit()
            logging.info(f"Stored/Updated {len(processed_prices)} prices in the database.")

    except sqlite3.Error as e:
        logging.error(f"Database error during price storage: {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred during price storage: {e}")


# --- Main Job ---
def price_update_job():
    """The main job to be scheduled."""
    logging.info("Running price update job...")
    raw_data = fetch_prices()
    if raw_data:
        processed_data = process_prices(raw_data)
        store_prices(processed_data)
    logging.info("Price update job finished.")

# --- Scheduler ---
if __name__ == "__main__":
    logging.info("Starting Price Miner App...")
    setup_database()

    # Schedule the job
    schedule.every(FETCH_INTERVAL_MINUTES).minutes.do(price_update_job)

    # Run the job immediately first time
    price_update_job()

    # Keep the script running to execute scheduled jobs
    while True:
        schedule.run_pending()
        time.sleep(1)