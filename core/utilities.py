import requests
import pandas as pd
from config import logger
import aiohttp
from core.db import db, User_Query
from datetime import datetime, timezone


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
    

