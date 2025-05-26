import telebot
import os
from dotenv import load_dotenv
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import re
import gspread
from datetime import datetime
import base64

# Load environment variables from .env file
load_dotenv()

# Replace 'YOUR_BOT_TOKEN' with your actual bot token
BOT_TOKEN = os.getenv('TELE_TOKEN')

# running locally to connect google sheets
# JSON_TOKEN = os.getenv('JSON_PATHNAME')
# gc = gspread.service_account(filename=JSON_TOKEN)


# Running on render server
google_credentials = os.getenv("GOOGLE_CREDS")
gc = gspread.service_account(filename="google_credentials")
sh = gc.open("AL25 Everbridge Tracking")

# Initialize the bot
bot = telebot.TeleBot(BOT_TOKEN)

# Store user sessions in memory (for a live bot, consider a DB)
user_sessions = {}

# Cache the headers for optimization
HEADER_CACHE = {}

# Define the sequential steps with button prompts
steps = [
    "left_sunway", "at_30_min_mark", "reached_rest_stop", 
    "left_rest_stop", "reached_my_custom", "left_my_custom",
    "reached_sg_custom", "left_sg_custom", "reached_star"
]

# Human-readable prompts for each step
prompts = {
    "left_sunway": "Have you left Sunway?",
    "at_30_min_mark": "Are you at the 30 minutes mark?",
    "reached_rest_stop":  "Have you reached the rest stop?",
    "left_rest_stop":  "Have you left the rest stop?",
    "reached_my_custom": "Have you reached MY Customs?",
    "left_my_custom": "Have you left MY Customs?",
    "reached_sg_custom": "Have you reached SG Customs?",
    "left_sg_custom": "Have you left SG Customs?",
    "reached_star": "Have you reach Star? 🎉🚌"
}

# Doing this so that we can recover lost sessions by making it globally available

step_to_column = {
    "left_sunway": "Time departed from Sunway",
    "at_30_min_mark": "Time reach 30 min mark",
    "reached_rest_stop":  "Time Reach Rest Stop",
    "left_rest_stop": "Time Leave Rest Stop",
    "reached_my_custom": "Time reach MY custom",
    "left_my_custom": "Time leave MY custom",
    "reached_sg_custom": "Time reach SG custom",
    "left_sg_custom": "Time leave SG custom",
    "reached_star": "Time bus reach Star"
}

def intercept_end_command(message, next_handler):
    if message.text.strip().lower() == '/end':
        return end_bot(message)
    else:
        return next_handler(message)

# Entry point
@bot.message_handler(commands=['start'])
def handle_start(message):
    bot.send_message(message.chat.id, "🚌 Welcome! Please enter the *bus number* to begin or resume tracking:", parse_mode="Markdown")
    bot.register_next_step_handler(message, lambda msg: intercept_end_command(msg,ask_and_validate_bus_number))

def is_valid_bus_number(text):
    return re.fullmatch(r"[A-Za-z]{1,2}[0-9]{1,2}", text.strip()) is not None

def handle_bus_recovery_check(message):
    chat_id = message.chat.id
    bus_number = message.text.strip()

    session = recover_session_from_sheet(chat_id, bus_number)

    if session:
        user_sessions[chat_id] = session
        bot.send_message(chat_id, f"🔄 Resuming tracking for *Bus {bus_number}* from checkpoint {session['step_index'] + 1}.", parse_mode="Markdown")
        send_step_prompt(chat_id)
    else:
        user_sessions[chat_id] = {"step_index": 0, "bus_number": bus_number}
        bot.send_message(chat_id, "🆕 New bus detected. Please enter the *Wave number* (1–5):", parse_mode="Markdown")
        bot.register_next_step_handler(message, lambda msg: intercept_end_command(msg,handle_wave_number))

def ask_wave_number(message):
    user_sessions[message.chat.id] = {"step_index": 0}
    bot.send_message(message.chat.id, "Please enter the *Wave number* (single digit):", parse_mode="Markdown")
    bot.register_next_step_handler(message, lambda msg: intercept_end_command(msg,handle_wave_number))



def ask_bus_number(message):
    # user_sessions[message.chat.id] = {"step_index": 0}
    bot.send_message(message.chat.id, "Please enter the bus number:")
    #input data handling to sheets here
    bot.register_next_step_handler(message, lambda msg: intercept_end_command(msg, ask_and_validate_bus_plate))

def handle_wave_number(message):
    chat_id = message.chat.id
    wave = message.text.strip()

    if not wave.isdigit() or not (1 <= int(wave) <= 9):
        bot.send_message(chat_id, "❌ Please enter a valid Wave number (1–5).")
        return bot.register_next_step_handler(message,lambda msg: intercept_end_command(msg, handle_wave_number))

    user_sessions[chat_id]['wave'] = wave
    bot.send_message(chat_id, "Please enter the *CGs' names* (comma-separated if more than one):", parse_mode="Markdown")
    bot.register_next_step_handler(message,lambda msg: intercept_end_command(msg, handle_cgs_input))



def handle_cgs_input(message):
    chat_id = message.chat.id
    cgs = message.text.strip()

    if not cgs:
        bot.send_message(chat_id, "❌ Please enter valid CGs' names.")
        return bot.register_next_step_handler(message, lambda msg: intercept_end_command(msg,handle_cgs_input))

    user_sessions[chat_id]['cgs'] = cgs
    bot.send_message(chat_id, "Please enter the *bus plate number*:", parse_mode="Markdown")
    bot.register_next_step_handler(message, lambda msg: intercept_end_command(msg, ask_and_validate_bus_plate))

# @bot.message_handler(commands=['edit'])
def edit_details(message):
    chat_id = message.chat.id
    # user_sessions[chat_id] = {"step_index": 0}  # Reset session

    msg = bot.send_message(
        chat_id,
        "🔁 You’ve chosen to edit details.\nPlease re-enter the *bus number:*",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(msg, lambda msg1: intercept_end_command(msg1,ask_and_validate_bus_number))


def ask_and_validate_bus_number(message):
    chat_id = message.chat.id
    bus_number = message.text.strip()

    if not is_valid_bus_number(bus_number):
        bot.send_message(chat_id, "❌ Please enter a valid bus number (e.g., A1, B2).")
        return bot.register_next_step_handler(message, lambda msg: intercept_end_command(msg, ask_and_validate_bus_number))
    
    if chat_id not in user_sessions:
        user_sessions[chat_id] = {}

    user_sessions[chat_id]['bus_number'] = bus_number

    # Try to recover session from sheet
    session = recover_session_from_sheet(chat_id, bus_number)

    if session:
        user_sessions[chat_id] = session
        bot.send_message(chat_id, f"🔄 Resuming tracking for *Bus {bus_number}* from checkpoint {session['step_index'] + 1}.", parse_mode="Markdown")
        send_step_prompt(chat_id)
    else:
        user_sessions[chat_id] = {"step_index": 0, "bus_number": bus_number}
        bot.send_message(chat_id, "🆕 New bus detected. Please enter the *Wave number* (1–5):", parse_mode="Markdown")
        bot.register_next_step_handler(message, handle_wave_number)

def ask_and_validate_bus_plate(message):
    chat_id = message.chat.id
    plate = message.text.strip().upper()

    if not re.fullmatch(r"(?=.*[A-Z])[A-Z0-9\- ]{3,15}", plate):
        bot.send_message(chat_id, "❌ Please enter a valid bus plate number (e.g. 'ABC1234' or 'SGX-1234').")
        return bot.register_next_step_handler(message, lambda msg: intercept_end_command(msg,ask_and_validate_bus_plate))

    user_sessions[chat_id]['bus_plate'] = plate
    bot.send_message(chat_id, "Please enter the Bus IC's name:")
    bot.register_next_step_handler(message, lambda msg: intercept_end_command(msg,ask_bus_ic_name))


def ask_bus_plate_number(message):
    chat_id = message.chat.id
    plate = message.text.strip().upper()

    # Basic validation: alphanumeric + hyphens
    if not re.fullmatch(r"[A-Z0-9\- ]{3,15}", plate):
        bot.send_message(chat_id, "❌ Please enter a valid bus plate number (e.g. 'ABC1234' or 'SGX-1234').")
        return bot.register_next_step_handler(message, lambda msg: intercept_end_command(msg,ask_bus_plate_number))

    user_sessions[chat_id]['bus_plate'] = plate
    bot.send_message(chat_id, "Please enter the Bus IC's name:")
    bot.register_next_step_handler(message, lambda msg: intercept_end_command(msg,ask_bus_ic_name))


def ask_bus_ic_name(message):
    chat_id = message.chat.id
    name = message.text.strip()

    if not is_valid_name(name):
        bot.send_message(chat_id, "❌ Please enter a valid name for the Bus IC (letters only).")
        return bot.register_next_step_handler(message, lambda msg: intercept_end_command(msg, ask_bus_ic_name))

    user_sessions[chat_id]['bus_ic'] = name
    bot.send_message(chat_id, "Please enter the Bus 2IC's name:")
    bot.register_next_step_handler(message, lambda msg: intercept_end_command(msg, ask_2ic))


def ask_2ic(message):
    chat_id = message.chat.id
    if not is_valid_name(message.text):
        bot.send_message(chat_id, "❌ Please enter a valid name for the Bus 2IC (letters only).")
        return bot.register_next_step_handler(message, lambda msg: intercept_end_command(msg,ask_2ic))

    user_sessions[chat_id]['bus_2ic'] = message.text
    bot.send_message(chat_id, "Please enter the total number of people on board:")
    bot.register_next_step_handler(message, lambda msg: intercept_end_command(msg,ask_passenger_count))


def ask_passenger_count(message):
    chat_id = message.chat.id
    passenger_count = message.text.strip()

    # Store first
    user_sessions[chat_id]['passenger_count'] = passenger_count

    # Then validate
    if not passenger_count.isdigit():
        bot.send_message(chat_id, "❌ Please enter a valid number for passenger count.")
        return bot.register_next_step_handler(message, lambda msg: intercept_end_command(msg,ask_passenger_count))

    # If valid, proceed
    confirm_user_details(message)



def confirm_user_details(message):
    chat_id = message.chat.id
    session = user_sessions[chat_id]  #
    # user_sessions[chat_id]['passenger_count'] = message.text
    session['passenger_count'] = message.text.strip()

    # Assign row dynamically
    row = get_or_create_user_row(session['bus_number'])
    session['row'] = row  # Store for future logging

    session = user_sessions[chat_id]
    summary = (
    f"🚌 *Your entered details:*\n\n"
    f"*Bus Number:* {session['bus_number']}\n"
    f"*Wave:* {session['wave']}\n"
    f"*CGs:* {session['cgs']}\n"
    f"*Bus Plate:* {session['bus_plate']}\n"
    f"*Bus IC:* {session['bus_ic']}\n"
    f"*Bus 2IC:* {session['bus_2ic']}\n"
    f"*Passenger Count:* {session['passenger_count']}\n\n"
    f"✅ If everything is correct, click *Continue*.\n"
    f"🔁 If you'd like to change anything, click *Edit*."
    )


    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("✅ Continue", callback_data="confirm_details"),
        InlineKeyboardButton("🔁 Edit", callback_data="edit_details")
    )

    bot.send_message(chat_id, summary, reply_markup=markup, parse_mode="Markdown")

def start_checkpoint_flow(message):
    # user_sessions[message.chat.id]['passenger_count'] = message.text
    send_step_prompt(message.chat.id)

def send_step_prompt(chat_id):
    step_index = user_sessions[chat_id]["step_index"]
    if step_index >= len(steps):
        bot.send_message(chat_id,
            "🎉 Congratulations! You've successfully reached Star safely. "
            "Thank you for your effort 🙌\nPlease send /end to terminate this bot."
        )
        return
    step_key = steps[step_index]
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton(text="✅ Yes", callback_data=f"yes_{step_key}"),
        InlineKeyboardButton(text="⬅️ Back", callback_data="go_back")
    )
    bot.send_message(chat_id, f"{prompts[step_key]} (Click only when confirmed)", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def handle_step_callback(call):
    chat_id = call.message.chat.id
    session = user_sessions.get(chat_id)

    if not session:
        bot.send_message(chat_id, "Session not found. Please /start again.")
        return

    data = call.data

    

    if data == "go_back":
        if session["step_index"] > 0:
            clear_cell(chat_id)
            session["step_index"] -= 1
            current_step = steps[session["step_index"]]
            print(f"[ACTION] ⬅️ User {chat_id} went back to step index {session['step_index']} ({current_step})")
            
            # NEW: Inform the user they went back
            bot.send_message(
                chat_id,
                f"⬅️ You have moved back to: *{prompts[current_step]}*",
                parse_mode="Markdown"
            )
        else:
            print(f"[INFO] ⬅️ User {chat_id} already at first step, can't go back further")
            bot.send_message(chat_id, "⚠️ You're already at the first checkpoint. Cannot go back further.")

        send_step_prompt(chat_id)


   
    elif data.startswith("yes_"):
        print(f"[CALLBACK] ✅ Button Pressed: {data}")  # ✅ log button press
        step_key = data[4:]
        expected_step = steps[session["step_index"]]
        print(f"[DEBUG] step_key: {step_key}, expected_step: {expected_step}, step_index: {session['step_index']}")

        if step_key == expected_step:
            # log_to_excel_placeholder(chat_id, step_key)
            session['awaiting_passenger_count_step'] = step_key

            # 🎯 Custom reminder after MY Customs
            if step_key == "left_sg_custom":
                bot.send_message(
                    chat_id,
                    "🔔 *Reminder for Bus IC:*\nPlease put back the event signages at the:\n"
                    "- 🪧 *Front*\n"
                    "- 🔲 *Left side*\n"
                    "- 🪧 *Rear* of the bus.",
                    parse_mode="Markdown"
                )


            prompt_passenger_count(chat_id, step_key)
            # bot.register_next_step_handler(message, handle_passenger_count_after_step)
        else:
            print("[WARNING] Mismatch: button step vs current expected step")

            
    elif call.data == "confirm_details":
        chat_id = call.message.chat.id

        # 🔧 Log to the sheet now
        log_initial_details_to_sheet(chat_id)

        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🟢 Okay", callback_data="begin_checklist"))
        bot.send_message(chat_id, "Great! Please click the button below to begin the journey checklist.", reply_markup=markup)

    elif call.data == "begin_checklist":
       start_checkpoint_flow(call.message)

    elif call.data == "edit_details":
        # bot.send_message(call.message.chat.id, "Let’s start over. Please enter the bus number:")
        user_sessions[call.message.chat.id] = {"step_index": 0}
        edit_details(call.message) 

def prompt_passenger_count(chat_id, step_key):
    user_sessions[chat_id]['awaiting_passenger_count_step'] = step_key
    msg = bot.send_message(
        chat_id,
        f"👥 Please enter the *current passenger count* after '{prompts[step_key]}':",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(msg, lambda msg1: intercept_end_command(msg1,handle_passenger_count_after_step))

    

def handle_passenger_count_after_step(message):
    chat_id = message.chat.id
    passenger_count = message.text.strip()
    print(f"[INPUT] 👥 Received passenger count: '{passenger_count}' from user {chat_id}")

    if not passenger_count.isdigit():
        print("[ERROR] ❌ Invalid passenger count input")
        bot.send_message(chat_id, "❌ Please enter a valid number for passenger count.")
        return bot.register_next_step_handler(message, lambda msg: intercept_end_command(msg,handle_passenger_count_after_step))

    step_key = user_sessions[chat_id].get('awaiting_passenger_count_step')
    if not step_key:
        print("[ERROR] ❌ Missing step key during count logging")
        bot.send_message(chat_id, "⚠️ No step context found. Please try again.")
        return

    #handle if the passenger count does not match the original number
    current_pax = int(passenger_count)
    expected_pax = int(user_sessions[chat_id].get('passenger_count', current_pax))
    
    if 'passenger_log' not in user_sessions[chat_id]:
        user_sessions[chat_id]['passenger_log'] = []

    print(f"[DEBUG] expected: {expected_pax}, current: {current_pax}")

    if current_pax != expected_pax:
        user_sessions[chat_id]['pending_pax_mismatch'] = {
            'step_key': step_key,
            'actual_count': current_pax,
            'expected_count': expected_pax
        }
        msg = bot.send_message(
            chat_id,
            f"⚠️ Passenger count mismatch (Expected: {expected_pax}, Now: {current_pax}).\n"
            f"Please enter a reason to include in the Remarks column:"
        )
        return bot.register_next_step_handler(msg, lambda msg1: intercept_end_command(msg1,handle_mismatch_reason))

    user_sessions[chat_id]['passenger_log'].append({
        'step': step_key,
        'count': int(passenger_count)
    })

    print(f"[LOG] ✅ Saved count: {passenger_count} for step: {step_key} (User: {chat_id})")
    print(f"[STATE] Full log for user {chat_id}: {user_sessions[chat_id]['passenger_log']}")

    # ✅ NEW: Log time + checkbox to Google Sheet
    log_checkpoint_to_sheet(chat_id, step_key)

    bot.send_message(chat_id, "✅ Passenger count recorded.")
    user_sessions[chat_id]['step_index'] += 1
    send_step_prompt(chat_id)

def handle_mismatch_reason(message):
    chat_id = message.chat.id
    reason = message.text.strip()
    mismatch = user_sessions[chat_id].pop('pending_pax_mismatch', None)

    if not mismatch:
        bot.send_message(chat_id, "⚠️ No mismatch context found. Please retry the step.")
        return

    # Ensure passenger_log exists
    if 'passenger_log' not in user_sessions[chat_id]:
        user_sessions[chat_id]['passenger_log'] = []

    # Log count
    user_sessions[chat_id]['passenger_log'].append({
        'step': mismatch['step_key'],
        'count': mismatch['actual_count']
    })

    # ✅ Now log to sheet, with red remark
    log_checkpoint_to_sheet(
        chat_id,
        mismatch['step_key'],
        actual_pax=mismatch['actual_count'],
        expected_pax=mismatch['expected_count'],
        remark=reason
    )

    bot.send_message(chat_id, "✅ Passenger count and remark recorded.")
    user_sessions[chat_id]['step_index'] += 1
    send_step_prompt(chat_id)




#validation helper function.
def is_valid_name(text):
    return re.fullmatch(r"[A-Za-z\s\-]+", text.strip()) is not None



    
@bot.message_handler(commands=['end'])
def end_bot(message):
    chat_id = message.chat.id
    # user_sessions.pop(chat_id, None)
    bot.send_message(chat_id, "✅ Your session has been terminated. You can restart anytime with /start.")
    user_sessions.pop(message.chat.id, None)


# it will check by bus number and see if the user has an existing code
def get_or_create_user_row(bus_number):
    worksheet = sh.worksheet('D5')
    bus_numbers = worksheet.col_values(1)  # Assuming column A has bus numbers

    for i, existing in enumerate(bus_numbers):
        if existing.strip().lower() == bus_number.strip().lower():
            return i + 1  # gspread uses 1-based indexing

    # If not found, append a new row
    new_row_index = len(bus_numbers) + 1
    # worksheet.update_cell(new_row_index, 1, bus_number)
    return new_row_index


def clear_cell(chat_id):
    session = user_sessions[chat_id]
    step_index = session["step_index"]
    row = session.get("row", 2)

    col_time = 8 + (3 * step_index)
    col_true = 9 + (3 * step_index)
    worksheet = sh.worksheet('D5')
    worksheet.update_cell(row, col_time, '')
    worksheet.update_cell(row, col_true, '')
    print(f"[LOG] {chat_id} cleared step at row {row}")

# read the column head
# def get_column_mapping(worksheet):
#     header_row = worksheet.row_values(1)
#     return {header.strip().lower(): idx + 1 for idx, header in enumerate(header_row)}

def get_column_mapping(worksheet):
    title = worksheet.title  # e.g. 'D1'

    if title in HEADER_CACHE:
        return HEADER_CACHE[title]

    header_row = worksheet.row_values(1)
    column_map = {header.strip().lower(): idx + 1 for idx, header in enumerate(header_row)}

    HEADER_CACHE[title] = column_map
    return column_map


# this logs the bus number, bus plate, no. of pax, bus ic and bus 2ic down into the sheet.
def log_initial_details_to_sheet(chat_id):
    session = user_sessions[chat_id]
    row = session['row']
    worksheet = sh.worksheet('D5')
    columns = get_column_mapping(worksheet)

    try:
        worksheet.update(
            f"A{row}:G{row}",
            [[
                session['wave'],
                session['bus_number'],
                session['bus_plate'],
                session['passenger_count'],
                session['bus_ic'],
                session['bus_2ic'],
                session['cgs'],
            ]]
        )

    except KeyError as e:
        bot.send_message(chat_id, f"❌ Column header not found in sheet: {e}")
        print(f"[ERROR] Column not found: {e}")
        return
    except Exception as e:
        bot.send_message(chat_id, f"❌ Failed to update Google Sheet: {e}")
        print(f"[ERROR] Google Sheet update failed: {e}")
        return

    print(f"[LOG] Initial bus info saved dynamically for user {chat_id} at row {row}")

# this is code to log each checkpoint.
def log_checkpoint_to_sheet(chat_id, step_key, actual_pax=None, expected_pax=None, remark=None):
    session = user_sessions[chat_id]
    row = session['row']
    worksheet = sh.worksheet('D5')
    columns = get_column_mapping(worksheet)

    # step_to_column is a global var
    if step_key not in step_to_column:
        print(f"[INFO] No sheet mapping for step '{step_key}', skipping log.")
        return

    time_col_name = step_to_column[step_key].strip().lower()
    try:
        time_col_index = columns[time_col_name]
        tele_col_index = time_col_index + 1  # "Tele" column is always next
        remarks_col_index = tele_col_index + 1

        if remark:
            worksheet.update_cell(row, remarks_col_index, remark)
            worksheet.format(gspread.utils.rowcol_to_a1(row, remarks_col_index), {
                "backgroundColor": {"red": 1, "green": 0.8, "blue": 0.8}
            })
        else:
            worksheet.update_cell(row, remarks_col_index, "")
            worksheet.format(gspread.utils.rowcol_to_a1(row, remarks_col_index), {
            "backgroundColor": {"red": 1, "green": 1, "blue": 1}  # white background - reset the column if it was red.
            })

    except KeyError as e:
        print(f"[ERROR] Column header not found: {e}")
        return

    current_time = datetime.now().strftime("%H:%M")
    worksheet.update_cell(row, time_col_index, current_time)
    worksheet.update_cell(row, tele_col_index, True)

    print(f"[LOG] Logged step '{step_key}' at {current_time} for user {chat_id} in row {row}")

# if user filling halfway we recover the session.
def recover_session_from_sheet(chat_id, bus_number):
    worksheet = sh.worksheet('D5')

    columns = get_column_mapping(worksheet)
    bus_col_index = columns.get("bus #")  # Get index from header

    if not bus_col_index:
        print("[ERROR] 'Bus #' column not found in header.")
        return None

    bus_numbers = worksheet.col_values(bus_col_index)
    # bus_numbers = worksheet.col_values(2)  # Column 2 = "Bus #" (1-indexed)

    for i, b in enumerate(bus_numbers):
        if b.strip().lower() == bus_number.strip().lower():
            row = i + 1
            values = worksheet.row_values(row)
            col_map = get_column_mapping(worksheet)

            # Helper to safely extract a value by header name
            def safe_get(col_name):
                idx = col_map.get(col_name.strip().lower())
                return values[idx - 1].strip() if idx and len(values) >= idx else ""

            # Extract fields
            wave = safe_get("wave")
            cgs = safe_get("cgs")
            bus_plate = safe_get("bus plate")
            pax = safe_get("no. of pax")
            bus_ic = safe_get("bus ic")
            bus_2ic = safe_get("bus 2ic")

            # Step recovery
            step_index = 0
            for step in steps:
                col_name = step_to_column.get(step)
                col_idx = col_map.get(col_name.strip().lower())
                if col_idx and len(values) >= col_idx and values[col_idx - 1].strip():
                    step_index += 1
                else:
                    break

            return {
                "step_index": step_index,
                "bus_number": bus_number,
                "row": row,
                "wave": wave,
                "cgs": cgs,
                "bus_plate": bus_plate,
                "passenger_count": pax,
                "bus_ic": bus_ic,
                "bus_2ic": bus_2ic
            }

    return None

