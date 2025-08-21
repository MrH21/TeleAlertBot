from core.db import db, User_Query
from core.state import SELECTING_TICKER, SETTING_TARGET, SELECTING_DIRECTION, MAX_ALERTS
from core.utilities import get_plan, fetch_current_price
from config import logger
from telegram.ext import ContextTypes, ConversationHandler
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
import pandas as pd
from datetime import datetime, timedelta, timezone
from core.subscription import send_upgrade_invoice
import pytz

# Keyboard Ticker Options
keyboard_ticker = [['BTCUSDT', 'ETHUSDT'], ['XRPUSDT', 'SOLUSDT'], ['LINKUSDT','DOTUSDT'], ['ADAUSDT','BNBUSDT'], ['SUIUSDT','LTCUSDT']]
reply_markup_ticker = ReplyKeyboardMarkup(keyboard_ticker, one_time_keyboard=True, resize_keyboard=True)

  
async def help_command(update:Update, context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("*Here are the bot commands available:*\n\n/start - Getting started with this bot. \n/addalert - to set your crypto symbol and target for the alert."
                                    "\n/myalerts - to see what your current alerts are with option to delete.\n/help - see all commands available", parse_mode="Markdown")
    
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
            "alerts": [],
            "subscriber": False
        })
        await update.message.reply_text(
            "✨ Welcome to our *Crypto Alert Bot*!\n\n"
            "_You've been given a 7-day PREMIUM trial with up to 5 alerts.\n"
            "After that, you'll be limited to 1 alert unless you upgrade._\n"
            "*Proceed to /addalert now*",
            parse_mode="Markdown"
        )
    else:
        plan = await get_plan(user)
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

    plan = await get_plan(user)
    if plan == "free" and len(user["alerts"]) >= MAX_ALERTS[plan]:
        await update.message.reply_text(f"❌ You have reached your *{plan.upper()}* plan limit of *{MAX_ALERTS[plan]}* alerts.\n"
                                        "If you are on the FREE plan, you can upgrade to PREMIUM for more alerts. \nProceed to /upgrade to upgrade your plan.", parse_mode="Markdown")
        return ConversationHandler.END
    
    if plan == "premium" and len(user["alerts"]) >= MAX_ALERTS[plan]:
        await update.message.reply_text(f"❌ You have reached your *{plan.upper()}* plan limit of *{MAX_ALERTS[plan]}* alerts.", parse_mode="Markdown")
        return ConversationHandler.END

    keyboard_ticker = [
        [InlineKeyboardButton('BTCUSDT', callback_data="ticker_BTCUSDT")],
        [InlineKeyboardButton('ETHUSDT', callback_data="ticker_ETHUSDT")],
        [InlineKeyboardButton('XRPUSDT', callback_data="ticker_XRPUSDT")],
        [InlineKeyboardButton('SOLUSDT', callback_data="ticker_SOLUSDT")],
        [InlineKeyboardButton('LINKUSDT', callback_data="ticker_LINKUSDT")],
        [InlineKeyboardButton('DOTUSDT', callback_data="ticker_DOTUSDT")],
        [InlineKeyboardButton('ADAUSDT', callback_data="ticker_ADAUSDT")],
        [InlineKeyboardButton('BNBUSDT', callback_data="ticker_BNBUSDT")],
        [InlineKeyboardButton('SUIUSDT', callback_data="ticker_SUIUSDT")],
        [InlineKeyboardButton('LTCUSDT', callback_data="ticker_LTCUSDT")]
    ]
     
    reply_markup = InlineKeyboardButton(keyboard_ticker)
    await update.message.reply_text("📊 Select the ticker:", reply_markup=reply_markup)
    return SELECTING_TICKER

async def select_ticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # Acknowledge the callback query
    
    ticker = query.data.split("_", 1)[1]  # Extract ticker from callback data
    context.user_data["ticker"] = ticker
    
    current_price = await fetch_current_price(context.user_data["ticker"])
    await update.message.reply_text(f"🎯 Enter your target price for *{context.user_data['ticker']}* with current price of *{current_price:,.4f}*", parse_mode='Markdown')
    return SETTING_TARGET
    
async def select_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data["target"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number.")
        return SETTING_TARGET

    keyboard_direction = [
        [InlineKeyboardButton("↗ Price Above", callback_data="above")],
        [InlineKeyboardButton("↘ Price Below", callback_data="below")],
        ]
    reply_markup_direction = InlineKeyboardMarkup(keyboard_direction)
    
    await update.message.reply_text(f"⚠️ Do you want to be alerted when the price goes *ABOVE* or *BELOW* this target?"
                                    , parse_mode='Markdown',reply_markup=reply_markup_direction)
    return SELECTING_DIRECTION

async def select_direction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # Acknowledge the callback query
    
    if "ticker" not in context.user_data or "target" not in context.user_data:
        return
    
    direction = query.data
    now = pd.Timestamp.now()
    last_checked = now.isoformat()

    user_id = update.effective_user.id
    user = db.get(User_Query.user_id == user_id)
    
    if not user:
        await query.edit_message_text("❌ User not found. Please use /start first.")
        return ConversationHandler.END
    
    user["alerts"].append({
        "ticker": context.user_data["ticker"],
        "target": context.user_data["target"],
        "direction": direction,
        "last_checked": last_checked
    })
    db.update(user, User_Query.user_id == user_id)

    await query.edit_message_text(
        f"✅ Alert added: {context.user_data['ticker']} {direction.upper()} {context.user_data['target']}"
    )
    return ConversationHandler.END

# --- Retrieve all user alerts ---
async def myalerts(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id
    user = db.get(User_Query.user_id == user_id)
    
    if not user:
        await update.message.reply_text("❌ Please use /start first.")
        return 
    
    alerts = user.get("alerts",[])

    if not alerts:
        await update.message.reply_text("📭 You have no active alerts.")
        return

    text = "📋 *Your Current Alerts:*\n\n"
    keyboard = []
    # if user is on free plan and has more than 1 alert, only show the first alert and delete rest.
    if user["plan"] == "free":
        if len(alerts) > 1:
            text += "⚠️ You are on the FREE plan and can only have 1 alert. The rest will be deleted.\n\n"
            alerts = alerts[:1]
            db.update({"alerts": alerts}, User_Query.user_id == user_id)
        
        for idx, alert in enumerate(alerts, start=1):
            text += f"{idx}. {alert['ticker']} {alert['direction']} {alert['target']}\n"
            keyboard.append([InlineKeyboardButton(f"❌ Delete {idx}", callback_data=f"delete_{idx}")])

    elif user["plan"] == "premium":
        for idx, alert in enumerate(alerts, start=1):
            text += f"{idx}. {alert['ticker']} {alert['direction']} {alert['target']}\n"
            keyboard.append([InlineKeyboardButton(f"❌ Delete {idx}", callback_data=f"delete_{idx}")])
             
        if len(alerts) >= MAX_ALERTS["premium"]:
            text += f"⚠️ You have reached your limit of {MAX_ALERTS["premium"]} alerts."
            
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

# --- Delete alert ---
async def delete_alert_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    user = db.get(User_Query.user_id == user_id)
    
    if not user or not user.get("alerts"):
        await query.edit_message_text("📭 You have no active alerts.")
        return

    alerts = user.get("alerts", [])
    
    try:
        idx = int(query.data.split("_")[1]) - 1
    except (IndexError, ValueError):
        await query.edit_message_text("❌ Invalid alert index format.")
        return

    if 0 <= idx < len(alerts):
        removed = alerts.pop(idx)
        db.update({"alerts": alerts}, User_Query.user_id == user_id)
        await query.edit_message_text(
            f"🗑 Deleted alert: {removed['ticker']} {removed['direction']} {removed['target']}"
        )
    else:
        await query.edit_message_text("❌ Invalid alert index.")

# --- Upgrade plan ---
async def upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = db.get(User_Query.user_id == user_id)

    if not user:
        await update.message.reply_text("❌ Please use /start first.")
        return

    plan = await get_plan(user)
    subscribed = user.get("subscriber", False)
    trial_end = pd.Timestamp(user.get("trial_expiry", None)).tz_convert('UTC')
    trial_end_short = trial_end.strftime('%Y-%m-%d')  # Short date format
    now = pd.Timestamp.now(tz=pytz.UTC) # localized timestamp
    
    # if user is on trial version, can subscribe to premium plan - send user to lemon squeezy
    checkout_url = f"https://lupox.lemonsqueezy.com/checkout?telegram_id={user_id}"
    billing_url = f"https://lupox.lemonsqueezy.com/billing?telegram_id={user_id}"
    
    if plan == "premium" and trial_end > now and not subscribed:
        await update.message.reply_text(
            f"💳 You are currently on the <b>{plan.upper()}</b> plan with trial period ending <b>{trial_end_short}</b>\n\n"
            f"If you would like to subscribe to the Premium Plan you can here: <a href=\"{checkout_url}\"><b>Subscribe to Premium</b></a>"
            , parse_mode="HTML")
        return
    elif plan == "premium" and subscribed == True:
        await update.message.reply_text(
            f"💳 You are already subscribed to the <b>{plan.upper()}</b> plan.\n\n"
            f"To manage your active subscription, follow this link: <a href=\"{billing_url}\"><b>Manage Subscription</b></a>", parse_mode="HTML")
        return
    elif plan == "free":
        update.message.reply_text(
            f"💳 You are currently on the <b>{plan.upper()}</b> plan.\n\n"
            f"To subscribe to Premium, please follow this link: <a href=\"{checkout_url}\"><b>Subscribe to Premium</b></a>", parse_mode="HTML")
        return