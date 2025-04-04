import sqlite3
import logging
import os

# --- Configuration ---
DB_FILE = "prices.db"
LOG_FILE = "setup_db.log"

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler() # Also print to console
    ])

# --- Database Schema Definition ---

# SQL statement for the 'prices' table
CREATE_PRICES_TABLE = """
CREATE TABLE IF NOT EXISTS prices (
    caption TEXT PRIMARY KEY,    -- Unique name of the price item (e.g., "سکه امامی")
    value REAL NOT NULL,         -- Latest processed price value
    timestamp INTEGER NOT NULL   -- Unix timestamp of the last update
);
"""

# SQL statement for the 'users' table
CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    chat_id INTEGER PRIMARY KEY, -- Telegram user's unique chat ID
    username TEXT,               -- Telegram username (nullable)
    first_name TEXT,             -- Telegram first name (nullable)
    last_name TEXT,              -- Telegram last name (nullable)
    last_message_id INTEGER      -- ID of the last price update message sent (nullable)
);
"""

# SQL statement for the 'subscriptions' table
CREATE_SUBSCRIPTIONS_TABLE = """
CREATE TABLE IF NOT EXISTS subscriptions (
    chat_id INTEGER NOT NULL,   -- Foreign key to the users table
    caption TEXT NOT NULL,      -- The specific price item the user subscribed to

    -- Define composite primary key to ensure user subscribes to an item only once
    PRIMARY KEY (chat_id, caption),

    -- Define foreign key constraint: if a user is deleted, their subscriptions are also deleted
    FOREIGN KEY (chat_id) REFERENCES users(chat_id) ON DELETE CASCADE
);
"""

# Optional: Create an index for faster subscription lookups by chat_id
CREATE_SUBSCRIPTION_INDEX = """
CREATE INDEX IF NOT EXISTS idx_sub_chat_id ON subscriptions (chat_id);
"""

def create_database_schema():
    """
    Connects to the SQLite database (creating it if it doesn't exist)
    and executes the CREATE TABLE statements.
    """
    logging.info(f"Attempting to set up database schema in '{DB_FILE}'...")
    conn = None # Initialize connection variable
    try:
        # Connect to the database. Creates the file if it doesn't exist.
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        logging.info(f"Database connection established to '{DB_FILE}'.")

        # Enable Foreign Key constraint enforcement (important!)
        cursor.execute("PRAGMA foreign_keys = ON;")
        logging.info("Foreign key enforcement enabled.")

        # Execute table creation statements
        logging.info("Creating 'prices' table (if not exists)...")
        cursor.execute(CREATE_PRICES_TABLE)

        logging.info("Creating 'users' table (if not exists)...")
        cursor.execute(CREATE_USERS_TABLE)

        logging.info("Creating 'subscriptions' table (if not exists)...")
        cursor.execute(CREATE_SUBSCRIPTIONS_TABLE)

        logging.info("Creating index on 'subscriptions.chat_id' (if not exists)...")
        cursor.execute(CREATE_SUBSCRIPTION_INDEX)

        # Commit the changes
        conn.commit()
        logging.info("Database schema created/verified successfully.")

    except sqlite3.Error as e:
        logging.error(f"Database setup failed: {e}")
        # Rollback changes if any error occurred during transaction
        if conn:
            conn.rollback()
            logging.info("Database transaction rolled back due to error.")
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        if conn:
            conn.rollback()
            logging.info("Database transaction rolled back due to unexpected error.")
    finally:
        # Ensure the connection is closed even if errors occur
        if conn:
            conn.close()
            logging.info("Database connection closed.")

# --- Main Execution ---
if __name__ == "__main__":
    # Check if the DB file already exists (optional, for info)
    if os.path.exists(DB_FILE):
        logging.info(f"Database file '{DB_FILE}' already exists. Schema will be verified/updated.")
    else:
        logging.info(f"Database file '{DB_FILE}' not found. It will be created.")

    # Run the setup function
    create_database_schema()