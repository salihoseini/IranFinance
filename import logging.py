import logging
import sqlite3
import os
import jdatetime # For Shamsi date
from datetime import datetime
import asyncio # For potential sleeps if needed

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    PersistenceInput, # For user_data persistence (optional but good)
    DictPersistence,  # Simple dictionary-based persistence
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden # Specific Telegram errors

# --- Configuration ---
TELEGRAM_TOKEN = "7870608369:AAEtxEq3DYQgfMCmwMPO_E_dhhAk56SpNow" # Replace with your token
DB_FILE = "prices.db"
LOG_FILE = "telegram_bot.log"
UPDATE_INTERVAL_SECONDS = 60 # Send updates every 60 seconds

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ])
logger = logging.getLogger(__name__)

# --- Callback Data Constants ---
CALLBACK_DONE = "DONE_SELECT"
CALLBACK_PREFIX_TOGGLE = "TOGGLE_"

# --- Database Setup & Helpers ---
def setup_database():
    """Creates user-related tables if they don't exist."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            # Users table: Basic user info + last message ID for updates
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                last_message_id INTEGER
            )""")
            # Subscriptions table: Links users to the price captions they follow
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                chat_id INTEGER NOT NULL,
                caption TEXT NOT NULL,
                FOREIGN KEY (chat_id) REFERENCES users(chat_id),
                PRIMARY KEY (chat_id, caption)
            )""")
            # Optional: Index for faster lookups if needed later
            # cursor.execute("CREATE INDEX IF NOT EXISTS idx_sub_chat_id ON subscriptions (chat_id)")
            conn.commit()
            logger.info("User database setup complete.")
    except sqlite3.Error as e:
        logger.error(f"User database setup error: {e}")
        raise

def db_query(query, params=(), fetchone=False, commit=False):
    """General purpose DB query helper to reduce boilerplate."""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            if commit:
                conn.commit()
                return None # Or return affected rows if needed
            else:
                return cursor.fetchone() if fetchone else cursor.fetchall()
    except sqlite3.Error as e:
        logger.error(f"Database query error. Query: '{query}', Params: {params}. Error: {e}")
        # Depending on severity, you might want to return None or raise
        return None if fetchone else [] # Return empty list/None on error for reads

# --- User & Subscription Management ---
async def register_user(chat_id: int, username: str, first_name: str, last_name: str):
    """Adds or ignores a user in the users table."""
    query = """
    INSERT OR IGNORE INTO users (chat_id, username, first_name, last_name, last_message_id)
    VALUES (?, ?, ?, ?, NULL)
    """
    db_query(query, (chat_id, username, first_name, last_name), commit=True)
    logger.info(f"Registered/Verified user: {chat_id} ({username or 'No username'})")

def get_user_subscriptions(chat_id: int) -> list[str]:
    """Retrieves the list of captions a user is subscribed to."""
    query = "SELECT caption FROM subscriptions WHERE chat_id = ?"
    results = db_query(query, (chat_id,))
    return [row[0] for row in results]

def get_available_items() -> list[str]:
    """Gets distinct available price captions from the database."""
    query = "SELECT DISTINCT caption FROM prices ORDER BY caption"
    results = db_query(query)
    if not results:
        logger.warning("No price items found in the database. Miner might not be running.")
    return [row[0] for row in results]

def update_user_subscriptions(chat_id: int, captions: list[str]):
    """Updates a user's subscriptions atomically."""
    delete_query = "DELETE FROM subscriptions WHERE chat_id = ?"
    insert_query = "INSERT INTO subscriptions (chat_id, caption) VALUES (?, ?)"

    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            # Start transaction
            cursor.execute("BEGIN TRANSACTION")
            # Delete old subscriptions
            cursor.execute(delete_query, (chat_id,))
            # Insert new ones
            if captions:
                cursor.executemany(insert_query, [(chat_id, caption) for caption in captions])
            # Commit transaction
            cursor.execute("COMMIT")
            logger.info(f"Updated subscriptions for {chat_id}. New count: {len(captions)}")
    except sqlite3.Error as e:
        logger.error(f"Database error updating subscriptions for {chat_id}: {e}")
        try:
             conn.execute("ROLLBACK") # Rollback on error
        except: pass # Ignore rollback errors

# --- Telegram Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command."""
    user = update.effective_user
    if not user:
        logger.warning("Received /start but could not get user info.")
        return

    chat_id = user.id
    username = user.username
    first_name = user.first_name
    last_name = user.last_name

    await register_user(chat_id, username, first_name, last_name)

    # Initialize or clear temporary selection state in user_data
    context.user_data['temp_selection'] = set(get_user_subscriptions(chat_id)) # Pre-load current subs

    await send_item_selection_keyboard(chat_id, context, "سلام! لطفا موارد مورد نظر برای دریافت قیمت را انتخاب کنید:")

# --- Telegram Callback Query Handler ---
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles button presses from inline keyboards."""
    query = update.callback_query
    await query.answer() # Acknowledge callback quickly

    chat_id = query.message.chat_id
    message_id = query.message.message_id
    callback_data = query.data

    # Ensure temporary selection exists
    if 'temp_selection' not in context.user_data:
        context.user_data['temp_selection'] = set(get_user_subscriptions(chat_id)) # Initialize if missing


    if callback_data == CALLBACK_DONE:
        # --- User finished selection ---
        final_selection_set = context.user_data.get('temp_selection', set())
        final_selection_list = sorted(list(final_selection_set)) # Save sorted list

        update_user_subscriptions(chat_id, final_selection_list)
        del context.user_data['temp_selection'] # Clean up temp data

        confirmation_text = "✅ تنظیمات شما ذخیره شد.\n قیمت موارد زیر برای شما ارسال خواهد شد:\n\n"
        if final_selection_list:
            confirmation_text += "- " + "\n- ".join(final_selection_list)
        else:
            confirmation_text += "<i>هیچ موردی انتخاب نشده است.</i>"

        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=confirmation_text,
                parse_mode=ParseMode.HTML,
                reply_markup=None # Remove keyboard
            )
        except BadRequest as e:
            logger.warning(f"Could not edit message after selection for {chat_id} (maybe unchanged?): {e}")


    elif callback_data.startswith(CALLBACK_PREFIX_TOGGLE):
        # --- User toggled an item ---
        item_caption = callback_data[len(CALLBACK_PREFIX_TOGGLE):]
        temp_selection_set = context.user_data.get('temp_selection', set())

        if item_caption in temp_selection_set:
            temp_selection_set.remove(item_caption)
        else:
            temp_selection_set.add(item_caption)

        context.user_data['temp_selection'] = temp_selection_set # Save updated set

        # Update the keyboard message
        await edit_selection_keyboard(chat_id, message_id, context, "لطفا موارد مورد نظر را انتخاب کنید:")

# --- Keyboard Generation & Sending ---
def build_selection_keyboard(available_items: list[str], selected_items: set[str]) -> InlineKeyboardMarkup:
    """Builds the dynamic inline keyboard for item selection."""
    keyboard = []
    row = []
    items_per_row = 2

    for item in available_items:
        is_selected = item in selected_items
        button_text = ("✅ " if is_selected else "") + item
        row.append(InlineKeyboardButton(button_text, callback_data=CALLBACK_PREFIX_TOGGLE + item))
        if len(row) >= items_per_row:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("✅ ذخیره و پایان", callback_data=CALLBACK_DONE)])
    return InlineKeyboardMarkup(keyboard)

async def send_item_selection_keyboard(chat_id: int, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Sends the initial selection keyboard message."""
    available_items = get_available_items()
    if not available_items:
        await context.bot.send_message(chat_id, "متاسفانه در حال حاضر لیستی برای انتخاب وجود ندارد. لطفا بعدا دوباره /start را بزنید.")
        return

    selected_items_set = context.user_data.get('temp_selection', set())
    reply_markup = build_selection_keyboard(available_items, selected_items_set)

    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

async def edit_selection_keyboard(chat_id: int, message_id: int, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Edits the keyboard message during selection."""
    available_items = get_available_items() # Might need to refresh if items change? Unlikely mid-selection.
    selected_items_set = context.user_data.get('temp_selection', set())
    reply_markup = build_selection_keyboard(available_items, selected_items_set)

    try:
        await context.bot.edit_message_text( # Edit text too, in case instructions change
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
    except BadRequest as e:
        # Ignore if message is not modified
        if "Message is not modified" not in str(e):
            logger.warning(f"Failed to edit selection keyboard for {chat_id}: {e}")

# --- Price Update Sending Job ---
def get_shamsi_date() -> str:
    """Gets the current Shamsi date."""
    try:
        # Use jdatetime library
        now_gregorian = datetime.now()
        now_shamsi = jdatetime.datetime.fromgregorian(datetime=now_gregorian)
        # Format: YYYY/MM/DD (adjust as needed)
        return now_shamsi.strftime("%Y/%m/%d")
        # Alternative: Call the keybit API if preferred
        # response = requests.get("https://api.keybit.ir/time/")
        # response.raise_for_status()
        # return response.json()['date']['far']
    except Exception as e:
        logger.error(f"Failed to get Shamsi date: {e}")
        return "N/A"

def get_current_prices(captions: list[str]) -> dict[str, tuple[float, int]]:
    """Fetches current values and timestamps for specific captions from DB."""
    if not captions:
        return {}

    placeholders = ','.join('?' * len(captions))
    query = f"SELECT caption, value, timestamp FROM prices WHERE caption IN ({placeholders})"
    results = db_query(query, tuple(captions))

    # Create a dictionary for easy lookup
    price_dict = {row[0]: (row[1], row[2]) for row in results} # {caption: (value, timestamp)}
    return price_dict

async def send_updates_job(context: ContextTypes.DEFAULT_TYPE):
    """Job function run by JobQueue to send updates."""
    logger.info("Running scheduled update job...")

    # 1. Get all users who have subscriptions
    query_users = """
    SELECT DISTINCT u.chat_id, u.last_message_id
    FROM users u JOIN subscriptions s ON u.chat_id = s.chat_id
    """
    users_to_update = db_query(query_users)

    if not users_to_update:
        logger.info("No users with active subscriptions found.")
        return

    shamsi_date = get_shamsi_date()
    time_str = datetime.now().strftime("%H:%M:%S")
    message_footer = f"\n\n📡 <i>قیمت‌ها بروز هستند.</i>" # Simplified footer

    for chat_id, last_message_id in users_to_update:
        # 2. Get user's specific subscriptions
        user_subscriptions = get_user_subscriptions(chat_id)
        if not user_subscriptions:
            continue # Should not happen based on query_users, but check anyway

        # 3. Get current prices for subscribed items
        current_prices = get_current_prices(user_subscriptions)
        if not current_prices:
            logger.warning(f"No current prices found for subscriptions of user {chat_id}. Skipping.")
            continue # Skip user if their items aren't in the prices table

        # 4. Format message (No price comparison emoji here, just latest)
        message_body = ""
        has_data = False
        # Sort by caption maybe?
        for caption in sorted(user_subscriptions):
            if caption in current_prices:
                value, timestamp = current_prices[caption]
                # You could add logic here to compare with a 'previous_prices' cache
                # stored perhaps in context.bot_data if you want the 📈/📉 emojis back.
                # For simplicity now, just show the current value.
                message_body += f"🔹 <b>{caption}:</b> {value:,.0f} تومان\n\n" # Format as integer تومان
                has_data = True

        if not has_data:
            logger.info(f"No relevant price data found for user {chat_id} this cycle.")
            continue

        # 5. Construct and send/edit message
        message_header = f"📢 <b>آخرین قیمت‌ها (موارد انتخابی شما)</b>\n🗓 تاریخ: <b>{shamsi_date}</b>\n⏰ ساعت: <b>{time_str}\n\n"
        full_message = message_header + message_body.strip() + message_footer

        new_message_id = None
        try:
            if last_message_id:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=last_message_id,
                    text=full_message,
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"Edited message {last_message_id} for user {chat_id}")
            else:
                # Send new message if no previous ID
                sent_msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text=full_message,
                    parse_mode=ParseMode.HTML
                )
                new_message_id = sent_msg.message_id
                logger.info(f"Sent new message {new_message_id} to user {chat_id}")

        except BadRequest as e:
            if "Message to edit not found" in str(e) or "message can't be edited" in str(e) or "Message is not modified" in str(e):
                 logger.warning(f"Editing failed for user {chat_id}, msg_id {last_message_id}. Sending new message. Error: {e}")
                 try:
                     sent_msg = await context.bot.send_message(chat_id=chat_id, text=full_message, parse_mode=ParseMode.HTML)
                     new_message_id = sent_msg.message_id
                     logger.info(f"Sent new message {new_message_id} after edit failed for user {chat_id}")
                 except Exception as send_e:
                     logger.error(f"Failed to send new message to user {chat_id} after edit failure: {send_e}")
            else:
                 logger.error(f"Unhandled BadRequest sending/editing update for {chat_id}: {e}")
        except Forbidden as e:
            logger.warning(f"Bot blocked or kicked by user {chat_id}: {e}. Consider removing user/subs.")
            # Add logic here to potentially remove the user's subscriptions if blocked
        except Exception as e:
             logger.error(f"Unexpected error sending update to user {chat_id}: {e}")

        # 6. Update last_message_id in DB if a new message was sent
        if new_message_id:
             db_query("UPDATE users SET last_message_id = ? WHERE chat_id = ?", (new_message_id, chat_id), commit=True)


# --- Main Application Setup ---
if __name__ == "__main__":
    logger.info("Starting Telegram Bot App...")
    setup_database()

    # Optional: Setup persistence for user_data (to remember selections across restarts)
    # You might need to install `python-telegram-bot[persistence]`
    # persistence = DictPersistence() # Simple in-memory dict persistence
    # Consider PicklePersistence for saving to file:
    # from telegram.ext import PicklePersistence
    # persistence = PicklePersistence(filepath='bot_persistence.pickle')

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(TELEGRAM_TOKEN).build() # Add .persistence(persistence) if using it

    # Add command handlers
    application.add_handler(CommandHandler("start", start))

    # Add callback query handler
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    # Add the repeating job to the queue
    job_queue = application.job_queue
    job_queue.run_repeating(send_updates_job, interval=UPDATE_INTERVAL_SECONDS, first=10, name="send_price_updates") # Start after 10 sec

    logger.info("Bot polling started...")
    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)

    logger.info("Bot stopped.")