from core.db import db, User_Query
from core.state import SELECTING_TICKER, SETTING_TARGET, SELECTING_DIRECTION, MAX_ALERTS, SELECTING_TICKER_INSIGHTS, SET_PARAMS
from core.utilities import get_plan, fetch_current_price, get_ticker_keyboard
from indicators.data_processing import process_indicators, create_price_chart_with_levels
from paypal.client import PayPalClient
from paypal.subscriptions import create_subscription
from config import logger, ADMIN_ID, PAYPAL_CLIENT_ID, PAYPAL_SECRET, PAYPAL_MODE, PAYPAL_PLAN_ID
import asyncio
from telegram.ext import ContextTypes, ConversationHandler, CallbackContext
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
import pandas as pd
from datetime import datetime, timedelta, timezone
import pytz
import base64
import io
from tinydb.operations import set

# Initialize cache
from core.cache import CachedSymbolData
cache = CachedSymbolData()

# Initialize PayPal client
paypal_client = PayPalClient(PAYPAL_CLIENT_ID, PAYPAL_SECRET, sandbox=(PAYPAL_MODE == "sandbox"))

# Keyboard Ticker Options
keyboard_ticker = [['BTCUSDT', 'ETHUSDT'], ['XRPUSDT', 'SOLUSDT'], ['LINKUSDT','DOTUSDT'], ['ADAUSDT','BNBUSDT'], ['SUIUSDT','LTCUSDT']]
reply_markup_ticker = ReplyKeyboardMarkup(keyboard_ticker, one_time_keyboard=True, resize_keyboard=True)

  
async def help_command(update:Update, context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("*Here are the bot commands available:*\n\n/start - Getting started with this bot. \n/addalert - To set your crypto symbol and target for the alert."
                                    "\n/myalerts - To see what your current alerts are with option to delete."
                                    "\n/insights - To get market insights on selected crypto using technical indicators."
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
            "ml_timeline": "1d",
            "paypal_sub_id": None,
            "paypal_status": False
        })
        await update.message.reply_text(
            "✨ Welcome to *Crypto Alert Bot*! ✨\n\n"
            "You've been given a 7-day PREMIUM trial with up to 8 price alerts. As well as deeper market insights based on technical indicators, support and resistance levels "
            "which is calculated using machine learning.\n\n"
            "After that, you'll be limited to 2 price alerts unless you /upgrade.\n\n"
            "*Proceed to /addalert now*",
            parse_mode="Markdown"
        )
    else:
        plan = await get_plan(user)
        await update.message.reply_text(
            f"✨✨ *WELCOME BACK!* ✨✨\n\n"
            f"You are on the *{plan.upper()}* plan "
            f"with {MAX_ALERTS[plan]} alert(s) allowed.\n\n"
            f"*Subscriber Status*: {'✅ Subscribed' if user.get('paypal_status', False) else '❌ Not Subscribed'}\n\n",
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

    await update.message.reply_text("📊 Select the ticker:", reply_markup=get_ticker_keyboard(columns=2))
    return SELECTING_TICKER

# --- Setting the symbol for add alert ---
async def select_ticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:        
        query = update.callback_query
        await query.answer()  # Acknowledge the callback query
        
        ticker = query.data.replace("ticker_", "")
        context.user_data["ticker"] = ticker
        
        current_price = await fetch_current_price(ticker)
        await query.edit_message_text(f"🎯 Enter target price for *{context.user_data['ticker']}* with current price *${current_price:,.4f}*", parse_mode='Markdown')
        
        return SETTING_TARGET
    except Exception as e:
        logger.error(f"Error in select_ticker: {e}")
        await update.message.reply_text("❌ An error occurred. Please try again.")
        return ConversationHandler.END

# --- Choose the target price for alert ---    
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

# --- Set the direction of price movement ---
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
            f"🗑 *Deleted alert:* {removed['ticker']} {removed['direction']} {removed['target']}", parse_mode="Markdown"
        )
    else:
        await query.edit_message_text("❌ Invalid alert index.")
        
# --- Select insights target ---
async def insight_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = db.get(User_Query.user_id == user_id)

    if not user:
        await update.message.reply_text("❌ Please use /start first.")
        return ConversationHandler.END

    plan = await get_plan(user)
    if plan == "free" and len(user["alerts"]) >= MAX_ALERTS[plan]:
        await update.message.reply_text(f"❌ You are currently on the *{plan.upper()}* and don't have access to get crypto insights.\n"
                                        "You can upgrade to PREMIUM for dynamic insight on tokens. \nProceed to /upgrade to upgrade your plan.", parse_mode='Markdown')
        return ConversationHandler.END

    await update.message.reply_text("📊 Select a symbol below: Note - allow few seconds for insights and chart generation", reply_markup=get_ticker_keyboard(columns=2))
    return SELECTING_TICKER_INSIGHTS
  
# --- Market Insights handler ---
async def insights(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    # Handle the callback from ticker selection
    if query:
        await query.answer()
        ticker = query.data.replace("ticker_", "")
        context.user_data["ticker"] = ticker
    else:
        # If no query, this is being called directly (shouldn't happen in normal flow)
        await update.message.reply_text("Send /insights again to select a ticker.")
        return ConversationHandler.END

    user_id = update.effective_user.id
    user = db.get(User_Query.user_id == user_id)

    if not user:
        await query.edit_message_text("❌ Please use /start first.")
        return ConversationHandler.END

    plan = await get_plan(user)

    if plan == "free":
        await query.edit_message_text(
            "❌ This is a Premium feature. You will need to /upgrade to use.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    price = await fetch_current_price(ticker)
    last_entry = cache.retreive_last(ticker)
    if last_entry is not None:
        print(f"CACHE: Last entry from cache for {ticker} retrieved.")

    if last_entry is None:
        last_entry = process_indicators(ticker)
        print("CACHE: No cached data, retreiving fresh data.")
        # Save the freshly processed insights to cache
        try:
            cache.save_data(ticker, process_indicators, create_price_chart_with_levels)
            print(f"CACHE: Successfully saved insights for {ticker} to cache.")
        except Exception as e:
            logger.error(f"Error saving insights to cache for {ticker}: {e}")

    ema_insight = last_entry.get('ema_insight', '')
    macd_insight = last_entry.get('macd_insight', '')
    rsi_insight = last_entry.get('rsi_insight', '')
    macd_trend = last_entry.get('macd_trend', '')
    last_rsi = last_entry.get('rsi', 0)
    trend = last_entry.get('trend', '')
    sr_insight = last_entry.get('sr_insight', '')
    overall = last_entry.get('overall', '')
    confidence = last_entry.get('confidence', 0)
    
    # --- message formatting ---
    if "nearing" in sr_insight.lower():
        msg = f"With the current price - ${price:.4f} nearing key levels, watch out for possible breakout."
    elif "approaching" in sr_insight.lower():
        msg = f"The current price of - ${price:.4f} is approaching key levels, possible rejection ahead."
    else:
        msg = f"With the current price - ${price:.4f} trading between key levels, momentum could shift."

    if confidence < 4:
        conf_meaning = "Market signals are mixed; caution advised."
    elif 4 <= confidence <= 6:
        conf_meaning = "Possible reaction at key levels; wait for confirmation."
    else:
        conf_meaning = "Strong alignment across indicators."

    combined_insight = (
        f"*EMA200*: {ema_insight}\n\n"
        f"*MACD*: {macd_insight}\n\n"
        f"*RSI* ({last_rsi:.2f}): {rsi_insight}\n\n"
        f"*Support & Resistance*: {sr_insight}\n\n"
        f"📝 *Analyst Summary*: \n\n"
        f"Momentum: *{macd_trend.upper()}*\n"
        f"Trend context: *{trend.upper()}*\n"
        f"RSI momentum: *{('strong' if last_rsi > 60 else 'balanced' if 40 <= last_rsi <= 60 else 'weak')}*\n\n"
        f"{msg}\n\n"
        f"Overall bias: *{overall.upper()}*, confidence 🌡 *{confidence}/10* — {conf_meaning}"
    )

    await query.message.reply_text(
        f"💡 *Market Insights - {ticker}:* _(on last completed 1h candle)_ \n\n{combined_insight}",
        parse_mode="Markdown"
    )

    chart = cache.convert_to_image(ticker)
    try:
        if chart is None:
            img_b64 = create_price_chart_with_levels(ticker)
            img_bytes = base64.b64decode(img_b64)
            gen_chart = io.BytesIO(img_bytes)
            await context.bot.send_photo(
                chat_id=user_id,
                photo=gen_chart,
                caption="📈 Price Chart with Key Levels",
                parse_mode="Markdown"
            )
        else:
            img_bytes = base64.b64decode(chart)
            img_stream = io.BytesIO(img_bytes)
            img_stream.name = f"{ticker}.png"
            await context.bot.send_photo(
                chat_id=user_id,
                photo=img_stream,
                caption="📈 Price Chart with Key Levels",
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Error sending chart image for {ticker} to user {user_id}: {e}")
        await query.message.reply_text("❌ An error occurred while sending the price chart.")
    
    return ConversationHandler.END
  
# --- Set the Machine Learning parameters ---
async def set_params(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = db.get(User_Query.user_id == user_id)

    if not user:
        await update.message.reply_text("❌ Please use /start first.")
        return

    plan = await get_plan(user)
    
    keyboard_ticker = [
        [InlineKeyboardButton('⏰ Interval ~ 30min', callback_data="timeline_30m")],
        [InlineKeyboardButton('⏰ Interval ~ 1hr', callback_data="timeline_1h")],
        [InlineKeyboardButton('⏰ Interval ~ 4hr', callback_data="timeline_4h")],
        [InlineKeyboardButton('⏰ Interval ~ 6hr', callback_data="timeline_6h")],
        [InlineKeyboardButton('⏰ Interval ~ 1day', callback_data="timeline_1d")]
    ]     
    reply_markup = InlineKeyboardMarkup(keyboard_ticker)
    
    if plan == "free":
        await update.message.reply_text(f"❌ This is a Premium feature. You will need to /updgrade to use.", parse_mode="Markdown")
    
    if plan == "premium":
        await update.message.reply_text(f"🛠 *Machine Learning* 🛠 \n\n"
        "This bot uses Machine Learning to calculate support and resistance levels on daily timeframe. You can adjust timeframe to one of following: ", reply_markup=reply_markup, parse_mode="Markdown")

# --- ML Timeline button handler ---
async def params_button_handler(update: Update, context:CallbackContext):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    user = db.get(User_Query.user_id == user_id)

    if not user:
        await update.message.reply_text("❌ Please use /start first.")
        return
    
    clock = query.data.replace("timeline_", "")
    context.user_data["ml_timeline"] = clock
    
    db.update(set("ml_timeline", clock), User_Query.user_id == user_id)
    await query.edit_message_text(f"✅ Timeframe set to *{clock}*", parse_mode="Markdown")
    
# --- Upgrade plan ---
async def upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = db.get(User_Query.user_id == user_id)

    if not user:
        await update.message.reply_text("❌ Please use /start first.")
        return

    plan = await get_plan(user)
    
    trial_end = pd.Timestamp(user.get("trial_expiry", None)).tz_convert('UTC')
    trial_end_short = trial_end.strftime('%Y-%m-%d')  # Short date format
    now = pd.Timestamp.now(tz=pytz.UTC) # localized timestamp

    paypal_active = user.get("paypal_status", False)

    # Already Subscribed
    if paypal_active:
        await update.message.reply_text(
            "💳 You are already subscribed to the <b>PREMIUM</b> plan.\n\n"
            "To manage your subscription visit:\n"
            "https://www.paypal.com/myaccount/autopay/",
            parse_mode="HTML"
        )
        return
    
    # Active Trial
    if plan == "premium" and trial_end and trial_end > now:
        trial_end_short = trial_end.strftime('%Y-%m-%d')

        await update.message.reply_text(
            f"💳 You are currently on the <b>PREMIUM</b> trial.\n"
            f"Trial ends on <b>{trial_end_short}</b>.\n\n"
            "You can subscribe now to avoid interruption.",
            parse_mode="HTML"
        )
        return
    
    # Need new subscription
    subscription = create_subscription(
        client=paypal_client,
        plan_id=PAYPAL_PLAN_ID,
        return_url=f"https://yourdomain.com/paypal_return?user_id={user_id}",
        cancel_url=f"https://yourdomain.com/paypal_cancel?user_id={user_id}"
    )
    approval_url = subscription["approval_url"]

    db.update(
        {
            "paypal_sub_id": subscription["subscription_id"]
        },
        User_Query.user_id == user_id
    )

    await update.message.reply_text(
        "🚀 Upgrade to <b>PREMIUM</b>\n\n"
        f"<a href=\"{approval_url}\"><b>Subscribe Now</b></a>",
        parse_mode="HTML",
        disable_web_page_preview=True
    )


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
                
        message += (f"👥 Total Users: {total_users}\n"
                    f"💎 Total Subscribers: {total_subscribers}\n"
                    f"🆓 Free Plan Users: {total_free}\n"
                    f"⚡ Premium Plan Users: {total_premium}\n"
                    f"🚨 Total Alerts Set: {total_alerts}\n")
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        message += "❌ Error fetching statistics."
            
    await update.message.reply_text(message, parse_mode="Markdown")