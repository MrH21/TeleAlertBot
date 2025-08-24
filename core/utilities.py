import requests
import pandas as pd
from config import logger
import aiohttp
from core.db import db, User_Query
from datetime import datetime, timezone
from tinydb import TinyDB, Query
from xrpl.clients import JsonRpcClient
from xrpl.models.requests import Ledger

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
    
# --- Set up wallet database ---
wdb = TinyDB("exchange_wallets.js")
wallets_table = db.table("wallets")

# --- Set up tinydby if no wallet data ---
if len(wallets_table) == 0:
    wallets_table.insert_multiple([
        {"coin": "XRP", "address": "rs8ZPbYqgecRcDzQpJYAMhSxSi5htsjnza", "exchange": "Binance"},
        {"coin": "XRP", "address": "rPyCQm8E5j78PDbrfKF24fRC7qUAk1kDMZ", "exchange": "Bithump"},
        {"coin": "XRP", "address": "rsXT3AQqhHDusFs3nQQuwcA1yXRLZJAXKw", "exchange": "Uphold"},
        {"coin": "XRP", "address": "rMQ98K56yXJbDGv49ZSmW51sLn94Xe1mu1", "exchange": "Ripple"},
        {"coin": "XRP", "address": "rKveEyR1SrkWbJX214xcfH43ZsoGMb3PEv", "exchange": "Ripple"},
        {"coin": "XRP", "address": "rDxJNbV23mu9xsWoQHoBqZQvc77YcbJXwb", "exchange": "Upbit"},
        {"coin": "XRP", "address": "rw7m3CtVHwGSdhFjV4MyJozmZJv3DYQnsA", "exchange": "Bitbank"},
        {"coin": "XRP", "address": "r99QSej32nAcjQAri65vE5ZXjw6xpUQ2Eh", "exchange": "Coincheck"},
        {"coin": "BTC", "address": "34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo", "exchange": "Binance Cold Wallet"},
        {"coin": "BTC", "address": "bc1ql49ydapnjafl5t2cp9zqpjwe6pdgmxy98859v2", "exchange": "Robinhood Cold Wallet"},
        {"coin": "BTC", "address": "3M219KR5vEneNb47ewrPfWyb5jQ2DjxRP6", "exchange": "Binance Cold Wallet"},
        {"coin": "BTC", "address": "bc1qgdjqv0av3q56jvd82tkdjpy7gdp9ut8tlqmgrpmv24sq90ecnvqqjwvw97", "exchange": "Bitfinex Cold Wallet"}       
    ])

# -- XRP Ledger Client ---
client = JsonRpcClient("https://s2.ripple.com:51234/")

# --- Get the exchange by address ---
def get_exchange_by_address(address):
    Wallet = Query()
    result = wallets_table.get(Wallet.address == address)
    return result["exchange"] if result else None

# Fetch recent transactions over a threshold ---
def get_whale_txs(limit=5, min_xrp=500_000):
    ledger_req = Ledger(ledger_index="validated", transactions=True, expand=True)
    ledger_resp = client.request(ledger_req)
    txs = ledger_resp.result.get("ledger", {}).get("transactions",[])
    
    whales = []
    for tx in txs:
        if tx.get("TransactionType") == "Payment" and "Amount" in tx:
            try:
                amount_xrp = int(tx["Amount"])/ 1_000_000
                if amount_xrp >= min_xrp:
                    whales.append({
                        "amount": amount_xrp,
                        "from": tx["Account"],
                        "to": tx["Destination"],
                        "hash": tx["hash"]
                    })
            except Exception as e:
                logger.info(f"Exception with getting whale transactions: {e}")
                continue
            
    whales = sorted(whales, key=lambda x: x["amount"], reverse=True)
    return whales[:limit]

# --- Classify the whale transaction direction ---
def classify_whale_tx(tx):
    from_ex = get_exchange_by_address(tx["from"])
    to_ex = get_exchange_by_address(tx["to"])
    
    if to_ex:
        return "Exchange Inflow", to_ex, "🚨"
    elif from_ex: 
        return "Exchange Outflow", from_ex, "🟢"
    else:
        return "Unknown Transfer", None, "❓"
    
# --- Format the whale alert ---
def format_whale_alert(tx):
    xrp_price = fetch_current_price()
    classification, exchange, emoji = classify_whale_tx(tx)
    usd_value = tx["amount"] * xrp_price
    
    msg = (
        f"{emoji} *XRP Whale Alert*\n"
        f"{tx['amount']:,} XRP (~${usd_value:,.4f})\n"
        f"From: `{tx['from']}`\n"
        f"To: `{tx['to']}`\n"
        f"Type: *{classification}*"
    )
    if exchange:
        msg += f" ({exchange})"
    msg += f"\n[View Tx](https://xrpscan.com/tx/{tx['hash']})"
    return msg
