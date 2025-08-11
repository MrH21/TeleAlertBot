from core.db import db, User
from core.state import SELECTING_TICKER, CONFIRM_TICKER_CHANGE
from core.utilities import fetch_current_price, check_target
from config import logger
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters, ConversationHandler
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
import pandas as pd

# Keyboard Ticker Options
keyboard_ticker = [['BTCUSDT', 'ETHUSDT'], ['XRPUSDT', 'SOLUSDT'], ['ADAUSDT','BNBUSDT']]
reply_markup = ReplyKeyboardMarkup(keyboard_ticker, one_time_keyboard=True, resize_keyboard=True)

async def start(update:Update, context:ContextTypes.DEFAULT_TYPE):
    logger.info("User has started the bot")
    keyboard = [
        ["/setticker"],
        ["/settarget"],
        ["/myticker"],
        ["/myalert"],
        ["/help"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("✨ Welcome to *Crypto Alert Bot*! Set the crypto pair you are interested in and then you can set your price target. If that price target was reached you will receive an alert message. \n\n💡_A premium version of this bot will be coming soon!_", parse_mode='Markdown')
    
async def help_command(update:Update, context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("*Here are the basic commands available:*\n\n/setticker - to set your crypto symbol \n/settarget - to set your target price and direction eg. /settarget below 3.3321 \n/myticker - to see what your current selected symbol is \n/myalert - to see what your current alert is set to", parse_mode="Markdown")
    
async def setticker(update:Update, context:ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = db.get(User.user_id == user_id)
    
    if user_data and user_data.get('target') and user_data.get('direction'):
        context.user_data['changing_ticker'] = True
        await update.message.reply_text(
            "⚠️ You already have an active alert. You only have 1 alert on this Lite version of app. Changing the ticker will remove it. Do you want to continue? (Yes/No)",
            reply_markup=ReplyKeyboardMarkup([['Yes', 'No']], one_time_keyboard=True, resize_keyboard=True)
        )
        return CONFIRM_TICKER_CHANGE
    else:
        await update.message.reply_text("Please choose a ticker:", reply_markup=reply_markup)
        return CONFIRM_TICKER_CHANGE  # Reuse this state to capture selected ticker
    
async def confirm_or_set_ticker(update, context):
    user_id = update.effective_user.id
    text = update.message.text.upper()
    
    if text == "NO":
        await update.message.reply_text("✅ Ticker change cancelled.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    if text == "YES":
        # Clear alert
        db.update({'target': None, 'direction': None}, User.user_id == user_id)
        await update.message.reply_text("✅ Alert cleared. Now choose a new ticker:", reply_markup=reply_markup)
        return CONFIRM_TICKER_CHANGE

    # Assume it's a ticker now
    if text in sum(keyboard_ticker, []):  # Flatten list of ticker options
        db.upsert({'user_id': user_id, 'ticker': text}, User.user_id == user_id)
        await update.message.reply_text(f"✅ Ticker set to *{text}*", reply_markup=ReplyKeyboardRemove(), parse_mode='Markdown')
        return ConversationHandler.END
    else:
        await update.message.reply_text("❌ Invalid selection. Choose a ticker from the keyboard.")
        return CONFIRM_TICKER_CHANGE
    
    # --- Handle User Selection ---
async def handle_ticker_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = update.message.text.upper()
    valid_symbols = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT', 'SOLUSDT', 'ADAUSDT', 'BNBUSDT']    
    
    if symbol in valid_symbols:
        user_id = update.effective_user.id
        db.upsert({'user_id': user_id, 'ticker': symbol}, User.user_id ==user_id)
        
        price = fetch_current_price(symbol)
        
        if price:
            await update.message.reply_text(f"✅ Ticker set to *{symbol}*\n🏷 Current price ${price:,.4f}", parse_mode='Markdown')
            
            command_keyboard = [['/setticker', '/settarget'],['/myticker'],['/myalert']]
            reply_markup = ReplyKeyboardMarkup(command_keyboard, resize_keyboard=True)
            await update.message.reply_text("Choose an option:", reply_markup=reply_markup)
            return ConversationHandler.END
        else:
            await update.message.reply_text("⚠️ Failed to retrieve data. Try another symbol.")
            return SELECTING_TICKER
        
    else:
        await update.message.reply_text("❌ Invalid ticker. Please choose using /setticker.")
        return SELECTING_TICKER
    
# --- Set the price target ---
async def settarget(update:Update, context:ContextTypes.DEFAULT_TYPE):
    try:
        direction = context.args[0].lower()
        price_target = float(context.args[1])
        
        if direction not in ["above", "below"]:
            raise ValueError("Invalid direction")
        
        user_id = update.effective_user.id        
        record = db.get(User.user_id == user_id) or {}
        record.update({
            'target': price_target,
            'direction': direction
        })
        db.upsert(record, User.user_id == user_id)
        
        await update.message.reply_text(f"✅ Target set: Notify when price goes {direction} ${price_target:,.4f}")
        
    except (IndexError, ValueError):
        await update.message.reply_text("Invalid input: Use command followed by the movement direction and target price. Eg. /settarget above 3.24")


# --- Current Ticker Selected ---
async def myticker(update:Update, context: ContextTypes.DEFAULT_TYPE):
    record = db.get(User.user_id == update.effective_user.id)
    symbol = record['ticker'] if record and 'ticker' in record else "XRPUSDT"
    
    price = await fetch_current_price(symbol)
    await update.message.reply_text(f"📌 CURRENT SYMBOL: *{symbol}* with current price of ${price:,.4f}", parse_mode='Markdown')    
    
# --- Current Alert Set ---
async def myalert(update:Update, context: ContextTypes.DEFAULT_TYPE):
    record = db.get(User.user_id == update.effective_user.id)
    symbol = record['ticker'] if record and 'ticker' in record else "XRPUSDT"
    direction = record['direction'] if record and 'direction' in record else None
    target = record['target'] if record and 'target' in record else None
    if target is not None:
        await update.message.reply_text(f"📌 CURRERT ALERT: Price of {symbol} {direction} ${target:,.4f}", parse_mode='Markdown')
    else:
        await update.message.reply_text("💡 No alert has been set")

# --- Scheduled Alert ---   
async def scheduled_alert(app):
    users_with_targets = db.search((User.target != None) & (User.direction != None))
    logger.info(f"Found {len(users_with_targets)} users with targets")
    
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
                f"📌 Want more alerts and interval options? Pro version coming soon!"
            )
            logger.info(f"🎯 Target hit for user {user_id}")
            db.update({'target':None, 'direction':None}, User.user_id == user_id)
            await app.bot.send_message(chat_id=user_id, text=msg, parse_mode='Markdown')
        else:
            logger.info(f"No target hit.")