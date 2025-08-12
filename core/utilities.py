import requests
import pandas as pd
from config import logger
import aiohttp
from core.db import db, User_Query
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import ContextTypes


# --- Get the membership status ---
async def get_plan(user):
    # check trial expiry and return current plan
    if user["plan"] == "premium" and datetime.now.timezone(timezone.utc) > datetime.fromisoformat(User_Query["trial_expiry"]):
        db.update({"plan": "free"}, User_Query.user_id == user["user_id"])
        user["plan"] = "free"
    return user["plan"]
        
# --- Fetch the current price of the ticker and save as float ---
async def fetch_current_price(symbol="XRPUSDT"):
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    response = requests.get(url)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = response.json()
                if 'price' in data:
                    return float(data['price'])
                else:
                    logger.error(f"Price key missing in response: {data}")
                    return None
    except Exception as e:
        logger.error(f"Error with fetching the live price: {e}")
        return None
    
# --- Check the current price against the selected price target ---
async def check_target(user_id, symbol):
    record = db.get(User_Query.user_id == user_id)
    
    if not record:
        return None, False, "N/A"
    
    symbol = record.get('ticker')
    price_target = record.get('target')
    direction = record.get('direction', 'above')
    
    if not symbol or price_target is None or direction not in ["above", "below"]:
        return None, False, "N/A"
    
    current_price = await fetch_current_price(symbol)
    if current_price is None:
        return None, False, "N/A"
    
    if direction == "above":
        hit = current_price >= price_target
    elif direction == "below":
        hit = current_price <= price_target
    else:
        hit = False
    
    return current_price, hit, pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    
