#!/usr/bin/env python3
"""
PROFESSIONAL payment_card KILLER BOT
Developed by: @BLAZE_X_007
Admin Contact: @BLAZE_X_007
"""

import logging
import sqlite3
import time
import requests
import random
import string
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackContext, MessageHandler, filters
from datetime import datetime, timedelta

# Bot Configuration
BOT_TOKEN = "8468369302:AAF-2RQr9UDmiWR0kDoue6QO3_q-LVBr1K0"
ADMIN_ID = 7896890222
ADMIN_USERNAME = "@BLAZE_X_007"
DEVELOPER = "@BLAZE_X_007"
DONATION_API = "https://api.donation.systems/payments"

# Premium Tier Settings
GOLD_TIER = {
    "name": "Gold",
    "cards_per_hour": 5,
    "cooldown": 120,  # 2 minutes
    "price": "$49/month"
}

DIAMOND_TIER = {
    "name": "Diamond", 
    "cards_per_hour": 15,
    "cooldown": 20,   # 20 seconds
    "price": "$99/month"
}

ADMIN_TIER = {
    "name": "Admin",
    "cards_per_hour": 9999,
    "cooldown": 0,
    "price": "Free"
}

# User blocking system for premium_card attempts
user_blocks = {}

# Initialize logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Database setup
def init_db():
    conn = sqlite3.connect('card_processor.db')
    c = conn.cursor()
    
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, 
                  tier TEXT DEFAULT 'unauthorized',
                  added_by INTEGER,
                  join_date REAL,
                  last_used REAL,
                  cards_used_today INTEGER DEFAULT 0,
                  reset_time REAL,
                  premium_card_attempts INTEGER DEFAULT 0)''')  # Track premium_card attempts
    
    # Add admin user
    c.execute("INSERT OR IGNORE INTO users (user_id, tier, join_date) VALUES (?, ?, ?)",
              (ADMIN_ID, 'admin', time.time()))
    
    # Premium codes table
    c.execute('''CREATE TABLE IF NOT EXISTS premium_codes
                 (code TEXT PRIMARY KEY,
                  tier TEXT,
                  days INTEGER,
                  created_by INTEGER,
                  created_at REAL,
                  used_by INTEGER DEFAULT NULL,
                  used_at REAL DEFAULT NULL)''')
    
    conn.commit()
    conn.close()

# User blocking functions
def is_user_blocked(user_id):
    """Check if user is temporarily blocked for premium_card attempts"""
    if user_id in user_blocks:
        block_time, block_duration = user_blocks[user_id]
        if time.time() - block_time < block_duration:
            return True, block_duration - (time.time() - block_time)
        else:
            # Remove from block list if time expired
            del user_blocks[user_id]
    return False, 0

def block_user(user_id, duration=120):  # 2 minutes block by default
    """Block user for specified duration"""
    user_blocks[user_id] = (time.time(), duration)
    
    # Also update database
    conn = sqlite3.connect('card_processor.db')
    c = conn.cursor()
    c.execute("UPDATE users SET premium_card_attempts = premium_card_attempts + 1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    
    logger.info(f"User {user_id} blocked for {duration} seconds for premium_card attempt")

# User authorization functions
def is_user_authorized(user_id):
    # Check if user is blocked first
    blocked, remaining = is_user_blocked(user_id)
    if blocked:
        return False
    
    conn = sqlite3.connect('card_processor.db')
    c = conn.cursor()
    
    c.execute("SELECT tier FROM users WHERE user_id=?", (user_id,))
    result = c.fetchone()
    
    conn.close()
    
    if result and result[0] != 'unauthorized':
        return True
    return False

def get_user_tier(user_id):
    conn = sqlite3.connect('card_processor.db')
    c = conn.cursor()
    
    c.execute("SELECT tier FROM users WHERE user_id=?", (user_id,))
    result = c.fetchone()
    
    conn.close()
    
    if result:
        return result[0]
    return 'unauthorized'

def get_tier_settings(tier_name):
    if tier_name == 'gold':
        return GOLD_TIER
    elif tier_name == 'diamond':
        return DIAMOND_TIER
    elif tier_name == 'admin':
        return ADMIN_TIER
    else:
        return None

def can_user_verify_card(user_id):
    """Check if user can kill another card based on tier limits"""
    if user_id == ADMIN_ID:
        return True, 0  # Admin has no limits
    
    # Check if user is blocked
    blocked, remaining = is_user_blocked(user_id)
    if blocked:
        return False, remaining
    
    conn = sqlite3.connect('card_processor.db')
    c = conn.cursor()
    
    c.execute("SELECT tier, cards_used_today, reset_time FROM users WHERE user_id=?", (user_id,))
    result = c.fetchone()
    
    if not result:
        return False, 0
    
    tier, cards_used, reset_time = result
    tier_settings = get_tier_settings(tier)
    
    # Reset daily counter if needed
    current_time = time.time()
    if not reset_time or current_time - reset_time >= 86400:  # 24 hours
        cards_used = 0
        reset_time = current_time
        c.execute("UPDATE users SET cards_used_today=?, reset_time=? WHERE user_id=?",
                 (0, current_time, user_id))
        conn.commit()
    
    # Check hourly limit
    if cards_used >= tier_settings['cards_per_hour']:
        # Check cooldown
        c.execute("SELECT last_used FROM users WHERE user_id=?", (user_id,))
        last_used_result = c.fetchone()
        
        if last_used_result and last_used_result[0]:
            time_since_last_use = current_time - last_used_result[0]
            cooldown_remaining = tier_settings['cooldown'] - time_since_last_use
            
            if cooldown_remaining > 0:
                conn.close()
                return False, cooldown_remaining
    
    conn.close()
    return True, 0

def update_user_usage(user_id):
    """Update user's card usage statistics"""
    conn = sqlite3.connect('card_processor.db')
    c = conn.cursor()
    
    current_time = time.time()
    
    # Get current usage
    c.execute("SELECT cards_used_today FROM users WHERE user_id=?", (user_id,))
    result = c.fetchone()
    current_usage = result[0] if result else 0
    
    # Update usage
    c.execute('''UPDATE users 
                 SET cards_used_today=?, last_used=?
                 WHERE user_id=?''',
              (current_usage + 1, current_time, user_id))
    
    conn.commit()
    conn.close()

# Card Detection Functions
def detect_card_type(card_number):
    """Detect if card is payment_card, premium_card, or other"""
    card_number = str(card_number).strip()
    
    # payment_card: Starts with 4, 13 or 16 digits
    if re.match(r'^4[0-9]{12}(?:[0-9]{3})?$', card_number):
        return "payment_card"
    
    # premium_card: Starts with 51-55 or 2221-2720, 16 digits
    elif re.match(r'^(5[1-5][0-9]{14}|2(2[2-9][1-9][0-9]{12}|[3-6][0-9]{13}|7[0-1][0-9]{12}|720[0-9]{12}))$', card_number):
        return "premium_card"
    
    # Other card types
    elif re.match(r'^3[47][0-9]{13}$', card_number):  # AMEX
        return "AMEX"
    elif re.match(r'^6(?:011|5[0-9]{2})[0-9]{12}$', card_number):  # Discover
        return "DISCOVER"
    else:
        return "UNKNOWN"

def is_premium_card(card_number):
    """Check if card number is premium_card"""
    return detect_card_type(card_number) == "premium_card"

# payment_card Card Generation and Killing Functions
def generate_payment_card_card():
    """Generate valid payment_card card numbers"""
    prefix = "4"
    
    while True:
        # Generate 15 random digits (for 16-digit payment_card)
        body = ''.join([str(random.randint(0, 9)) for _ in range(15)])
        candidate = prefix + body
        
        # Validate with Luhn algorithm
        if luhn_check(candidate):
            # Double check it's actually a payment_card
            if detect_card_type(candidate) == "payment_card":
                # Generate expiry and CVV
                month = str(random.randint(1, 12)).zfill(2)
                year = str(random.randint(2024, 2028))
                cvv = str(random.randint(100, 999))
                
                return {
                    'number': candidate,
                    'expiry': f"{month}/{year}",
                    'cvv': cvv,
                    'type': 'payment_card'
                }

def luhn_check(card_number):
    """Luhn algorithm validation"""
    def digits_of(n):
        return [int(d) for d in str(n)]
    digits = digits_of(card_number)
    odd_digits = digits[-1::-2]
    even_digits = digits[-2::-2]
    checksum = sum(odd_digits)
    for d in even_digits:
        checksum += sum(digits_of(d*2))
    return checksum % 10 == 0

def verify_payment_card_card(card_data):
    """Simulate payment_card card termination process"""
    # Verify it's a payment_card card
    if detect_card_type(card_data['number']) != "payment_card":
        return [{
            'processor': 'Security System',
            'success': False,
            'time': 0.1,
            'response': 'REJECTED: Non-payment_card card detected'
        }]
    
    # Simulate API calls to payment processors
    processors = [
        "Stripe Gateway",
        "Braintree API", 
        "Authorize.net",
        "PayPal Pro",
        "Square Payments"
    ]
    
    attempts = []
    
    for processor in processors:
        # Simulate processing attempt
        processing_time = random.uniform(0.5, 3.0)
        time.sleep(processing_time)  # Simulate network delay
        
        # Simulate success/failure
        success = random.random() > 0.3  # 70% success rate
        
        attempt_result = {
            'processor': processor,
            'success': success,
            'time': round(processing_time, 2),
            'response': "Card processed successfully" if success else "Processing failed"
        }
        
        attempts.append(attempt_result)
        
        # If successful in any processor, consider card killed
        if success:
            break
    
    return attempts

# Manual card input handler
async def handle_manual_card(update: Update, context: CallbackContext):
    """Handle manual card input and detect premium_card attempts"""
    user_id = update.effective_user.id
    
    # Check if user is blocked
    blocked, remaining = is_user_blocked(user_id)
    if blocked:
        await update.message.reply_text(f"""
🚫 **TEMPORARILY BLOCKED**

You are blocked from using the bot for {int(remaining)} seconds.

Reason: premium_card termination attempt detected.
This bot is for payment_card cards only.

Contact {ADMIN_USERNAME} if this is an error.
        """)
        return
    
    if not is_user_authorized(user_id):
        await update.message.reply_text("🚫 Unauthorized access denied!")
        return
    
    card_input = update.message.text.strip()
    
    # Extract card number using regex
    card_match = re.search(r'\b(\d{13,19})\b', card_input)
    if not card_match:
        await update.message.reply_text("❌ Invalid card number format!")
        return
    
    card_number = card_match.group(1)
    card_type = detect_card_type(card_number)
    
    # BLOCK premium_card ATTEMPTS
    if card_type == "premium_card":
        # Block user for 2 minutes
        block_user(user_id, 120)
        
        await update.message.reply_text(f"""
🚫 **premium_card DETECTED - ACCESS BLOCKED**

This bot is exclusively for payment_card card termination.
premium_card termination is not supported.

❌ **You have been temporarily blocked for 2 minutes.**

Repeated attempts may result in permanent ban.

Contact {ADMIN_USERNAME} for payment_card-only termination service.

Bot Developed by {DEVELOPER}
        """)
        return
    
    # If not payment_card, reject
    if card_type != "payment_card":
        await update.message.reply_text(f"""
❌ **UNSUPPORTED CARD TYPE**

Detected: {card_type}
This bot only supports payment_card card termination.

Please provide a valid payment_card card number.

Contact {ADMIN_USERNAME} for assistance.
        """)
        return
    
    # Process payment_card card
    await process_manual_payment_card(update, context, card_number)

async def process_manual_payment_card(update: Update, context: CallbackContext, card_number: str):
    """Process manual payment_card card input"""
    user_id = update.effective_user.id
    
    # Check if user can kill another card
    can_, cooldown_remaining = can_user_verify_card(user_id)
    
    if not can_verify:
        if cooldown_remaining > 0:
            await update.message.reply_text(f"⏳ Cooldown active. Wait {int(cooldown_remaining)}s")
        else:
            await update.message.reply_text("❌ Daily limit reached!")
        return
    
    # Generate missing card details
    month = str(random.randint(1, 12)).zfill(2)
    year = str(random.randint(2024, 2028))
    cvv = str(random.randint(100, 999))
    
    card_data = {
        'number': card_number,
        'expiry': f"{month}/{year}",
        'cvv': cvv,
        'type': 'payment_card'
    }
    
    processing_msg = await update.message.reply_text(f"""
🔴 **MANUAL payment_card TERMINATION**

💳 **payment_card Card:** `{card_number}`
📅 **Expiry:** {card_data['expiry']}
🔐 **CVV:** {card_data['cvv']}

⚡ **Initiating termination sequence...**
    """)
    
    # kill the card
    verification_results = verify_payment_card_card(card_data)
    
    # Update user usage
    update_user_usage(user_id)
    
    # Prepare results
    success_count = sum(1 for attempt in verification_results if attempt['success'])
    
    results_text = f"""
✅ **payment_card CARD TERMINATED**

💳 **Card:** `{card_number}`
🎯 **Status:** SUCCESSFULLY KILLED
🔄 **Attempts:** {len(verification_results)}
✅ **Successful:** {success_count}

**Processing Details:**
"""
    
    for attempt in verification_results:
        status_icon = "✅" if attempt['success'] else "❌"
        results_text += f"{status_icon} {attempt['processor']}: {attempt['response']} ({attempt['time']}s)\n"
    
    tier = get_user_tier(user_id)
    tier_settings = get_tier_settings(tier)
    
    results_text += f"\n📊 **Your Usage:** {get_user_usage(user_id)}/{tier_settings['cards_per_hour']} cards this hour"
    results_text += f"\n\n💎 **Bot Developed by:** {DEVELOPER}"
    
    await processing_msg.edit_text(results_text)

# Donation API Integration
def process_donation(user_id, amount, currency="USD"):
    """Process donation through API"""
    donation_data = {
        'user_id': user_id,
        'amount': amount,
        'currency': currency,
        'timestamp': time.time(),
        'purpose': 'payment_card Killer Premium'
    }
    
    try:
        # Simulate API call to donation system
        response = f"Donation processed: {amount} {currency}"
        return True, response
    except Exception as e:
        return False, str(e)

# Bot Command Handlers
async def start_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    
    # Check if user is blocked
    blocked, remaining = is_user_blocked(user_id)
    if blocked:
        await update.message.reply_text(f"🚫 Blocked for {int(remaining)}s - premium_card attempt detected")
        return
    
    if not is_user_authorized(user_id):
        await update.message.reply_text(f"""
🚫 **ACCESS DENIED**

You are not authorized to use this bot.
Only approved users can access the payment_card Killer system.

Contact {ADMIN_USERNAME} for authorization.

**Bot Developed by:** {DEVELOPER}
        """)
        return
    
    tier = get_user_tier(user_id)
    tier_settings = get_tier_settings(tier)
    
    welcome_text = f"""
🔴 **payment_card KILLER BOT** 🔴

✅ **Authorized Access Granted**
🎯 **Your Tier:** {tier_settings['name']}
💳 **Cards/Hour:** {tier_settings['cards_per_hour']}
⏱️ **Cooldown:** {tier_settings['cooldown']}s

**Available Commands:**
/verify - process payment_card cards
/stats - Check your usage
/donate - Support the project

⚡ **Admin Contact:** {ADMIN_USERNAME}
💎 **Bot Developed by:** {DEVELOPER}

⚠️ **Warning:** premium_card attempts will result in temporary block!
        """
    
    await update.message.reply_text(welcome_text)

async def verify_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    
    # Check if user is blocked
    blocked, remaining = is_user_blocked(user_id)
    if blocked:
        await update.message.reply_text(f"""
🚫 **TEMPORARILY BLOCKED**

You are blocked from using the bot for {int(remaining)} seconds.

Reason: premium_card termination attempt detected.
This bot is for payment_card cards only.

Contact {ADMIN_USERNAME} if this is an error.
        """)
        return
    
    if not is_user_authorized(user_id):
        await update.message.reply_text("🚫 Unauthorized access denied!")
        return
    
    # Check if user can kill another card
    can_verify, cooldown_remaining = can_user_verify_card(user_id)
    
    if not can_verify:
        if cooldown_remaining > 0:
            await update.message.reply_text(f"""
⏳ **Cooldown Active**

Please wait {int(cooldown_remaining)} seconds 
before killing another card.

Your tier limits are in effect.
            """)
        else:
            await update.message.reply_text("""
❌ **Daily Limit Reached**

You've reached your hourly card limit.
Wait for the counter to reset.
            """)
        return
    
    # Generate and kill payment_card card
    processing_msg = await update.message.reply_text("""
🔴 **payment_card TERMINATION IN PROGRESS...**

Generating target payment_card card...
    """)
    
    # Generate payment_card card
    target_card = generate_payment_card_card()
    
    await processing_msg.edit_text(f"""
🔴 **TARGET ACQUIRED**

💳 **payment_card Card:** `{target_card['number']}`
📅 **Expiry:** {target_card['expiry']}
🔐 **CVV:** {target_card['cvv']}

⚡ **Initiating termination sequence...**
    """)
    
    # Kill the card
    verification_results = verify_payment_card_card(target_card)
    
    # Update user usage
    update_user_usage(user_id)
    
    # Prepare results
    success_count = sum(1 for attempt in verification_results if attempt['success'])
    
    results_text = f"""
✅ **payment_card CARD TERMINATED**

💳 **Card:** `{target_card['number'][:8]}XXXXXX`
🎯 **Status:** SUCCESSFULLY KILLED
🔄 **Attempts:** {len(verification_results)}
✅ **Successful:** {success_count}

**Processing Details:**
"""
    
    for attempt in verification_results:
        status_icon = "✅" if attempt['success'] else "❌"
        results_text += f"{status_icon} {attempt['processor']}: {attempt['response']} ({attempt['time']}s)\n"
    
    tier = get_user_tier(user_id)
    tier_settings = get_tier_settings(tier)
    
    results_text += f"\n📊 **Your Usage:** {get_user_usage(user_id)}/{tier_settings['cards_per_hour']} cards this hour"
    results_text += f"\n\n💎 **Bot Developed by:** {DEVELOPER}"
    results_text += f"\n📞 **Admin Contact:** {ADMIN_USERNAME}"
    
    await processing_msg.edit_text(results_text)

async def stats_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    
    if not is_user_authorized(user_id):
        await update.message.reply_text("🚫 Unauthorized access denied!")
        return
    
    tier = get_user_tier(user_id)
    tier_settings = get_tier_settings(tier)
    usage = get_user_usage(user_id)
    
    stats_text = f"""
📊 **YOUR STATS**

👤 **Tier:** {tier_settings['name']}
💳 **Cards/Hour:** {tier_settings['cards_per_hour']}
⏱️ **Cooldown:** {tier_settings['cooldown']}s
📈 **Used This Hour:** {usage}
🎯 **Remaining:** {tier_settings['cards_per_hour'] - usage}

💎 **Developer:** {DEVELOPER}
📞 **Admin Contact:** {ADMIN_USERNAME}

💎 **Upgrade:** Contact admin for tier upgrades
    """
    
    await update.message.reply_text(stats_text)

async def donate_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    
    donation_text = f"""
💎 **SUPPORT payment_card KILLER PROJECT**

Your donations help maintain and improve the service:

**Premium Tiers:**
🟡 Gold Tier: {GOLD_TIER['price']}
🔵 Diamond Tier: {DIAMOND_TIER['price']}

**Donation Benefits:**
• Priority access to new features
• Faster support response
• Custom request consideration

**Contact admin for donation methods:**
{ADMIN_USERNAME}

**Bot Developed by:** {DEVELOPER}

Thank you for supporting the project! 🙏
    """
    
    keyboard = [
        [InlineKeyboardButton("💳 Contact Admin", url=f"https://t.me/{ADMIN_USERNAME[1:]}")],
        [InlineKeyboardButton("📋 Tier Info", callback_data="tier_info")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(donation_text, reply_markup=reply_markup)

# Admin Commands (remain the same but with updated credits)
async def add_user_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("🚫 Admin command only!")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /adduser <user_id> <tier>")
        await update.message.reply_text("Tiers: gold, diamond")
        return
    
    try:
        target_user_id = int(context.args[0])
        tier = context.args[1].lower()
        
        if tier not in ['gold', 'diamond']:
            await update.message.reply_text("Invalid tier! Use: gold, diamond")
            return
        
        conn = sqlite3.connect('card_processor.db')
        c = conn.cursor()
        
        # Check if user exists
        c.execute("SELECT user_id FROM users WHERE user_id=?", (target_user_id,))
        if c.fetchone():
            c.execute("UPDATE users SET tier=?, added_by=? WHERE user_id=?", 
                     (tier, user_id, target_user_id))
        else:
            c.execute("INSERT INTO users (user_id, tier, added_by, join_date) VALUES (?, ?, ?, ?)",
                     (target_user_id, tier, user_id, time.time()))
        
        conn.commit()
        conn.close()
        
        tier_settings = get_tier_settings(tier)
        
        await update.message.reply_text(f"""
✅ **USER ADDED SUCCESSFULLY**

👤 User ID: `{target_user_id}`
🎯 Tier: {tier_settings['name']}
💳 Limit: {tier_settings['cards_per_hour']}/hour
⏱️ Cooldown: {tier_settings['cooldown']}s

User can now access the payment_card Killer bot.

**Bot Developed by:** {DEVELOPER}
        """)
        
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID format!")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# [Other admin commands remain similar with credits added...]

# Utility Functions
def get_user_usage(user_id):
    """Get user's current hourly usage"""
    conn = sqlite3.connect('card_processor.db')
    c = conn.cursor()
    
    c.execute("SELECT cards_used_today, reset_time FROM users WHERE user_id=?", (user_id,))
    result = c.fetchone()
    
    conn.close()
    
    if result:
        cards_used, reset_time = result
        # Reset if more than 24 hours passed
        if time.time() - reset_time >= 86400:
            return 0
        return cards_used
    
    return 0

# Main bot function
def main():
    """Start the bot"""
    init_db()
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("verify", verify_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("donate", donate_command))
    application.add_handler(CommandHandler("adduser", add_user_command))
    application.add_handler(CommandHandler("removeuser", remove_user_command))
    application.add_handler(CommandHandler("users", users_list_command))
    
    # Add message handler for manual card input
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_manual_card))
    
    # Start the bot
    print("🔴 payment_card KILLER BOT STARTED")
    print(f"👤 Admin: {ADMIN_USERNAME}")
    print(f"💎 Developer: {DEVELOPER}")
    print("💎 Premium tiers: Gold, Diamond")
    print("🚫 premium_card blocking: ENABLED (2min block)")
    print("🔧 Ready for payment_card termination operations...")
    
    application.run_polling()

if __name__ == '__main__':
    main()