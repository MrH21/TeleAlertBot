from core.db import db, User_Query
from core.state import SELECTING_TICKER, SETTING_TARGET, SELECTING_DIRECTION, MAX_ALERTS
from core.utilities import get_plan, fetch_current_price, format_whale_alert
from core.cache import recent_whales_cache, MAX_WHALE_CACHE
from config import logger, ADMIN_ID
import asyncio
from telegram.ext import ContextTypes, ConversationHandler, CallbackContext
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
import pandas as pd
from datetime import datetime, timedelta, timezone
import pytz

# Keyboard Ticker Options
keyboard_ticker = [['BTCUSDT', 'ETHUSDT'], ['XRPUSDT', 'SOLUSDT'], ['LINKUSDT','DOTUSDT'], ['ADAUSDT','BNBUSDT'], ['SUIUSDT','LTCUSDT']]
reply_markup_ticker = ReplyKeyboardMarkup(keyboard_ticker, one_time_keyboard=True, resize_keyboard=True)

  
async def help_command(update:Update, context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("*Here are the bot commands available:*\n\n/start - Getting started with this bot. \n/addalert - To set your crypto symbol and target for the alert."
                                    "\n/myalerts - To see what your current alerts are with option to delete."
                                    "\n/whales - To see recent XRP whale transactions and enable/disable whale alerts."
                                    "\n/upgrade - To upgrade your plan to premium for more alerts and features."
                                    "\n/help - See all commands available", parse_mode="Markdown")
    
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
            "watch": "XRPUSDT",
            "watch_status": True,
            "subscriber": False
        })
        await update.message.reply_text(
            "✨ Welcome to our *Crypto Alert Bot*! ✨\n\n"
            "_You've been given a 7-day PREMIUM trial with up to 8 price alerts as well as a XRP whale movement alert.\n\n"
            "After that, you'll be limited to 2 alert unless you /upgrade._\n\n"
            "*Proceed to /addalert now*",
            parse_mode="Markdown"
        )
    else:
        plan = await get_plan(user)
        await update.message.reply_text(
            f"✨✨ *WELCOME BACK!* ✨✨\n\n"
            f"You are on the *{plan.upper()}* plan "
            f"with {MAX_ALERTS[plan]} alert(s) allowed.\n\n"
            f"*Subscriber Status*: {'✅ Subscribed' if user.get('subscriber', False) else '❌ Not Subscribed'}\n\n"
            f"*Whale Alerts*: {'✅ Enabled' if user.get('watch_status', False) else '❌ Disabled'}\n\n",
            parse_mode="Markdown"
        )
        
# --- Snapshot of the current prices ----
async def snapshot(update:Update, context: ContextTypes.DEFAULT_TYPE):

    message = f"👀 Snapshot of the symbol prices"
    
    xrp = await fetch_current_price("XRPUSDT")
    btc = await fetch_current_price("BTCUSDT")
    
    message += (f"XRP Ripple: {xrp:,.4f}\n"
                f"XRP Ripple: {xrp:,.4f}\n") 
    
    await update.message.reply_text(message, parse_mode="Markdown")

    
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
     
    reply_markup = InlineKeyboardMarkup(keyboard_ticker)
    await update.message.reply_text("📊 Select the ticker:", reply_markup=reply_markup)
    return SELECTING_TICKER

async def select_ticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()  # Acknowledge the callback query
        
        ticker = query.data.replace("ticker_", "")
        context.user_data["ticker"] = ticker
        
        current_price = await fetch_current_price(context.user_data["ticker"])
        await query.edit_message_text(f"🎯 Enter your target price for *{context.user_data['ticker']}* with current price of *{current_price:,.4f}*", parse_mode='Markdown')
        return SETTING_TARGET
    except Exception as e:
        logger.error(f"Error in select_ticker: {e}")
        await update.message.reply_text("❌ An error occurred. Please try again.")
        return ConversationHandler.END
    
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
    # if user is on free plan and has more than 2 alert, only show the two alerts and delete rest.
    if user["plan"] == "free":
        if len(alerts) > MAX_ALERTS["free"]:
            text += "⚠️ You are on the FREE plan and can only have 2 alerts. The rest will be deleted.\n\n"
            alerts = alerts[:2]
            db.update({"alerts": alerts}, User_Query.user_id == user_id)
        
        for idx, alert in enumerate(alerts, start=1):
            text += f"{idx}. {alert['ticker']} {alert['direction']} {alert['target']}\n"
            keyboard.append([InlineKeyboardButton(f"❌ Delete {idx}", callback_data=f"delete_{idx}")])

    elif user["plan"] == "premium":
        for idx, alert in enumerate(alerts, start=1):
            text += f"{idx}. {alert['ticker']} {alert['direction']} {alert['target']}\n"
            keyboard.append([InlineKeyboardButton(f"❌ Delete {idx}", callback_data=f"delete_{idx}")])
             
        if len(alerts) >= MAX_ALERTS["premium"]:
            text += f"⚠️ You have reached your limit of {MAX_ALERTS['premium']} alerts."
            
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
        
# --- Whale transaction watcher ---
async def whales(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = db.get(User_Query.user_id == user_id)
    
    if not user:
        await update.message.reply_text("❌ Please use /start first.")
        return
    
    plan = await get_plan(user)
    
    # Take the last 5 whale transactions
    preview = recent_whales_cache[-5:]

    #logger.info(f"Recent whale cache for user {user_id}: {preview} on whales command")
    
    keyboard = [
        [InlineKeyboardButton("✅ Enable XRP Alerts", callback_data="whale_on")],
        [InlineKeyboardButton("❌ Disable XRP Alerts", callback_data="whale_off")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if not preview:
        await update.message.reply_text(
            "🐋 RECENT WHALE TRANSACTIONS\n\n_No recent whale transactions found at the moment_", 
            parse_mode="Markdown", 
            reply_markup=reply_markup
        )
        return
    
    # Format messages
    xrp_price = await fetch_current_price("XRPUSDT")
    msgs = [format_whale_alert(tx, xrp_price) for tx in preview]
    header = f"🐋 *RECENT WHALE TRANSACTIONS*\n\n"
   
    full_msg = header + "\n\n".join(msgs)
    
    if plan == "premium":
        await update.message.reply_text(full_msg, parse_mode="Markdown", reply_markup=reply_markup)
    else:  # Free plan
        notice = "💡 You are currently on the *Free* plan. To get whale alerts /upgrade"
        await update.message.reply_text(notice, parse_mode="Markdown")

    
# --- Whale button handler ----
async def whale_button_handler(update: Update, context:CallbackContext):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    user = db.get(User_Query.user_id == user_id)
    
    if not user:
        await update.message.reply_text("❌ Please use /start first.")
        return
    
    if query.data == "whale_on":
        db.update({"watch_status": True}, User_Query.user_id == user_id)
        await query.edit_message_text("✅ Whale alerts enabled")
    elif query.data == "whale_off":
        db.update({"watch_status": False}, User_Query.user_id == user_id)
        await query.edit_message_text("❌ Whale alerts disabled.")
        
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

# --- Broadcast message to all users (admin only) ---
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # restrict to admin only
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Please provide a message to broadcast.")
        return
    
    message = " ".join(context.args)
    
    # fetch all user ids
    users = db.all()
    sent_count = 0
    failed_count = 0
    
    for user in users:
        user_id = user["user_id"]
        try:
            await context.bot.send_message(chat_id=user_id, text=message, parse_mode="Markdown")
            sent_count += 1
            await asyncio.sleep(0.5)  # slight delay to avoid hitting rate limits
        except Exception as e:
            logger.error(f"Failed to send message to {user_id}: {e}")
            failed_count += 1
            
    await update.message.reply_text(f"✅ Broadcast completed. Sent: {sent_count}, Failed: {failed_count}")
    
# --- Retrieve bot statistics (admin only) ---   
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # restrict to admin only
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    message = f"*📊 Bot Statistics:*\n\n"
    
    try:
        # fetch all user data
        total_users = len(db)
        total_subscribers = len([user for user in db.all() if user.get("subscriber", False)])
        total_free = len([user for user in db.all() if user.get("plan") == "free"])
        total_premium = len([user for user in db.all() if user.get("plan") == "premium"])
        total_alerts = sum(len(user.get("alerts", [])) for user in db.all())    
        total_whale_watchers = len([user for user in db.all() if user.get("watch_status", False)])
        
        message += (f"👥 Total Users: {total_users}\n"
                    f"💎 Total Subscribers: {total_subscribers}\n"
                    f"🆓 Free Plan Users: {total_free}\n"
                    f"⚡ Premium Plan Users: {total_premium}\n"
                    f"🚨 Total Alerts Set: {total_alerts}\n"
                    f"🐋 Total Whale Alert Subscribers: {total_whale_watchers}\n")
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        message += "❌ Error fetching statistics."
            
    await update.message.reply_text(message, parse_mode="Markdown")