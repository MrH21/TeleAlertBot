import requests
import pandas as pd
from config import logger
import aiohttp
from core.db import db, User_Query
from ripple.xrp_functions import get_candles
from datetime import datetime, timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    
# --- Inline Keyboard function ---
TICKERS = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT", "LINKUSDT", "DOTUSDT", "ADAUSDT", "BNBUSDT", "SUIUSDT", "LTCUSDT"]

def get_ticker_keyboard(columns: int = 2):
    keyboard =[]
    row = []
    for i, ticker in enumerate(TICKERS, start=1):
        button = InlineKeyboardButton(ticker, callback_data=f"ticker_{ticker}")
        row.append(button)
        if i % columns == 0:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)

# --- Get the membership status ---
async def get_plan(user):
    plan = user.get("plan", "free")
    trial_expiry_str = user.get("trial_expiry")
    
    if plan == "premium" and trial_expiry_str:
        trial_expiry = datetime.fromisoformat(trial_expiry_str)
        now = datetime.now(timezone.utc)
        if now > trial_expiry:
            # Update DB - assuming User_Query is your DB query handler
            db.update({"plan": "free"}, User_Query.user_id == user["user_id"])
            plan = "free"
            user["plan"] = plan
    return plan
        
# --- Fetch the current price of the ticker and save as float ---
async def fetch_current_price(symbol="XRPUSDT"):
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                if 'price' in data:
                    return float(data['price'])
                else:
                    logger.error(f"Price key missing in response: {data}")
                    return None
    except Exception as e:
        logger.error(f"Error with fetching the live price: {e}")
        return None
    
    
# --- Calculate price change percentage ---
def calculate_price_change(old_price, new_price):
    try:
        if old_price == 0:
            raise ValueError("Old price cannot be zero.")
        return round(((new_price - old_price) / old_price) * 100, 2)
    except Exception as e:
        logger.error(f"Error calculating price change: {e}")
        return None


    

