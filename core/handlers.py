from core.db import db, User_Query
from core.state import SELECTING_TICKER, SETTING_TARGET, SELECTING_DIRECTION, MAX_ALERTS
from core.utilities import get_plan, fetch_current_price, check_target
from config import logger
from telegram.ext import ContextTypes, ConversationHandler
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
import pandas as pd
from datetime import datetime, timedelta, timezone

# Keyboard Ticker Options
keyboard_ticker = [['BTCUSDT', 'ETHUSDT'], ['XRPUSDT', 'SOLUSDT'], ['LINKUSDT','DOTUSDT'], ['ADAUSDT','BNBUSDT'], ['SUIUSDT','LTCUSDT']]
reply_markup_ticker = ReplyKeyboardMarkup(keyboard_ticker, one_time_keyboard=True, resize_keyboard=True)

  
async def help_command(update:Update, context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("*Here are the basic commands available:*\n\n/setticker - to set your crypto symbol \n/settarget - to set your target price and direction "
                                    "eg. /settarget below 3.3321 \n/myticker - to see what your current selected symbol is \n/myalert - to see what your current alert is set to", parse_mode="Markdown")
    
# --- Starting function ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = db.get(User_Query.user_id == user_id)

    if not user:
        trial_end = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        db.insert({
            "user_id": user_id,
            "plan": "premium",
            "trial_expiry": trial_end,
            "alerts": []
        })
        await update.message.reply_text(
            "✨ Welcome to our *Crypto Alert Bot*!\n\n"
            "You've been given a 7-day PREMIUM trial with up to 5 alerts.\n"
            "After that, you'll be limited to 1 alert unless you upgrade.",
            parse_mode="Markdown"
        )
    else:
        plan = get_plan(user)
        await update.message.reply_text(
            f"Welcome back! You are on the *{plan.upper()}* plan "
            f"with {MAX_ALERTS[plan]} alert(s) allowed.",
            parse_mode="Markdown"
        )
    
# --- Add alert function ----
async def addalert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = db.get(User_Query.user_id == user_id)

    if not user:
        await update.message.reply_text("❌ Please use /start first.")
        return ConversationHandler.END

    plan = get_plan(user)
    if len(user["alerts"]) >= MAX_ALERTS[plan]:
        await update.message.reply_text(f"❌ You have reached your {plan.upper()} plan limit of {MAX_ALERTS[plan]} alerts.")
        return ConversationHandler.END

    keyboard_ticker = [
        ['BTCUSDT', 'ETHUSDT'], 
        ['XRPUSDT', 'SOLUSDT'], 
        ['LINKUSDT','DOTUSDT'],
        ['ADAUSDT','BNBUSDT'], 
        ['SUIUSDT','LTCUSDT']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard_ticker, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("📊 Select the ticker:", reply_markup=reply_markup)
    return SELECTING_TICKER

async def select_ticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["ticker"] = update.message.text.strip().upper()
    await update.message.reply_text(f"💰 Enter your target price for {context.user_data['ticker']}:")
    return SETTING_TARGET
    
async def select_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data["target"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number.")
        return SETTING_TARGET

    keyboard_direction = [["📈 Price Above", "📉 Price Below"]]
    reply_markup_direction = ReplyKeyboardMarkup(keyboard_direction, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text(
        "⚠️ Do you want to be alerted when the price goes above or below this target?",
        reply_markup=reply_markup_direction
    )
    return SELECTING_DIRECTION

async def select_direction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    direction_choice = update.message.text.strip()
    direction = "above" if "Above" in direction_choice else "below"

    user_id = update.effective_user.id
    user = db.get(User_Query.user_id == user_id)
    user["alerts"].append({
        "ticker": context.user_data["ticker"],
        "target": context.user_data["target"],
        "direction": direction
    })
    db.update(user, User_Query.user_id == user_id)

    await update.message.reply_text(
        f"✅ Alert added: {context.user_data['ticker']} {direction.upper()} {context.user_data['target']}"
    )
    return ConversationHandler.END

# --- Retrieve all user alerts ---
async def myalerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = db.get(User_Query.user_id == user_id)

    if not user or not user["alerts"]:
        await update.message.reply_text("📭 You have no active alerts.")
        return

    text = "📋 *Your Alerts:*\n\n"
    keyboard = []
    for idx, alert in enumerate(user["alerts"], start=1):
        text += f"{idx}. {alert['ticker']} {alert['direction']} {alert['target']}\n"
        keyboard.append([InlineKeyboardButton(f"❌ Delete {idx}", callback_data=f"delete_{idx}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

# --- Delete alert ---
async def delete_alert_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    user = db.get(User_Query.user_id == user_id)

    idx = int(query.data.split("_")[1]) - 1
    if 0 <= idx < len(user["alerts"]):
        removed = user["alerts"].pop(idx)
        db.update(user, User_Query.user_id == user_id)
        await query.edit_message_text(f"🗑 Deleted alert: {removed['ticker']} {removed['direction']} {removed['target']}")
    else:
        await query.edit_message_text("❌ Invalid alert index.")


# --- Scheduled Alert ---   
async def scheduled_alert(app):
    users_with_targets = db.search((User_Query.target != None) & (User_Query.direction != None))
    tot_users = len(db.all())
    logger.info(f"Found {len(users_with_targets)} users with targets out of {tot_users} users.")
    
    for record in users_with_targets:
        user_id = record['user_id']
        symbol = record.get('ticker')
        direction = record.get('direction')

        if not symbol:
            logger.warning(f"No symbol set for user {user_id}")
            continue
        
        close, hit, date = await check_target(user_id, symbol)
        
        if close is None:
            continue  # Skip users with invalid data
        
        if hit:
            msg = (
                f"📢 *PRICE ALERT!*\n"
                f"✅ Target hit: {symbol} went {direction} ${record['target']:,.4f} on {date}\n\n"
                f"The target has been cleared, please set new.\n\n"
                f"📌 Want more alerts and interval options? Premium version coming soon!"
            )
            logger.info(f"🎯 Target hit for user {user_id}")
            db.update({'target':None, 'direction':None}, User_Query.user_id == user_id)
            await app.bot.send_message(chat_id=user_id, text=msg, parse_mode='Markdown')
        else:
            logger.info(f"No target hit.")