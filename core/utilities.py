import requests
import pandas as pd
from config import logger
import aiohttp
from core.db import db, User_Query
from core.cache import recent_whales_cache, MAX_WHALE_CACHE
from core.wallets_data import wallets
from datetime import datetime, timezone
from tinydb import TinyDB, Query
import asyncio
from xrpl.asyncio.clients import AsyncJsonRpcClient
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
wdb = TinyDB("exchange_wallets.json")
wallets_table = wdb.table("wallets")

# --- Set up tinydby if no wallet data ---
if len(wallets_table) == 0:
    wallets_table.insert_multiple(wallets)

# -- XRP Ledger Client and global ledger tracker ---
last_ledger_index = None
client = AsyncJsonRpcClient("https://s2.ripple.com:51234/")

# --- Get the exchange by address ---
def get_exchange_by_address(address):
    Wallet = Query()
    result = wallets_table.get(Wallet.address == address)
    return result["exchange"] if result else None

# --- Extract XRP amount from various formats ---
def extract_xrp_amount(amount_field):
    if isinstance(amount_field, str):
        # Amount in drops
        return int(amount_field) / 1_000_000
    elif isinstance(amount_field, dict):
        # Amount as an object
        if amount_field.get("currency") == "XRP":
            return int(amount_field.get("value", 0))
    return 0

# --- Update recent whales cache ----
def update_recent_whales(new_whales: list[dict]):
    global recent_whales_cache
    existing_hashes = {tx["hash"] for tx in recent_whales_cache}
    
    for tx in new_whales:
        if tx["hash"] not in existing_hashes:
            recent_whales_cache.append(tx)
            
    if len(recent_whales_cache) > MAX_WHALE_CACHE:
        recent_whales_cache = recent_whales_cache[-MAX_WHALE_CACHE:]

# --- Fetch recent transactions over a threshold from last ledger ---
async def get_whale_txs(min_xrp=500_000, lookback_ledgers=100):
    """
    Fetch whale transactions (Payment & OfferCreate) since the last ledger index we checked.
    """
    global last_ledger_index, recent_whales_cache
    whales = []

    try:
        # Get latest validated ledger index
        ledger_req = Ledger(ledger_index="validated")
        ledger_resp = await client.request(ledger_req)
        latest_index = int(ledger_resp.result["ledger_index"])
    except Exception as e:
        logger.error(f"Error fetching latest ledger index: {e}")
        return []

    # Decide where to start
    start_index = (last_ledger_index + 1) if last_ledger_index else max(latest_index - lookback_ledgers + 1, 0)

    for idx in range(start_index, latest_index + 1):
        try:
            resp = await client.request(
                Ledger(ledger_index=idx, transactions=True, expand=True)
            )
            txs = resp.result.get("ledger", {}).get("transactions", [])
            print(f"Ledger {idx} fetched with {len(txs)} transactions")
            
        except Exception as e:
            logger.error(f"Error fetching ledger {idx}: {e}")
            continue
        
        '''
        if txs:
            print("Sample tx:", txs[0])
        '''

        for tx in txs:
            tx_json = tx.get("tx_json", {})
            tx_type = tx_json.get("TransactionType")
            amount_xrp = 0

            # --- Payment whales ---
            if tx_type == "Payment":
                try:
                    delivered = tx.get("meta", {}).get("delivered_amount", tx_json.get("Amount", 0))
                    if isinstance(delivered, str):
                        amount_xrp = int(delivered) / 1_000_000
                    elif isinstance(delivered, dict) and delivered.get("currency") == "XRP":
                        amount_xrp = float(delivered.get("value", 0))
                             
                    if amount_xrp >= min_xrp:
                        whales.append({
                            "amount": amount_xrp,
                            "from": tx_json.get("Account"),
                            "to": tx_json.get("Destination"),
                            "hash": tx["hash"],
                            "ledger_index": idx,
                            "type": "Payment"
                        })
                except Exception as e:
                    logger.info(f"Exception parsing Payment tx in ledger {idx}: {e}")
                    continue

            # --- Ignore OfferCreate / OfferCancel (DEX orders) ---
            # OfferExecute is where XRP actually moves on DEX
            elif tx_type == "OfferExecute":
                # Sum all XRP movement from meta nodes
                affected_nodes = tx.get("meta", {}).get("AffectedNodes", [])
                for node in affected_nodes:
                    if "DeletedNode" in node and node["DeletedNode"]["LedgerEntryType"] == "Offer":
                        final = node["DeletedNode"].get("FinalFields", {})
                        taker_gets = final.get("TakerGets")
                        taker_pays = final.get("TakerPays")

                        amount_xrp = 0
                        counterparty = final.get("Account")

                        # Figure out which side was XRP
                        if isinstance(taker_gets, str):
                            amount_xrp = int(taker_gets) / 1_000_000
                        elif isinstance(taker_pays, str):
                            amount_xrp = int(taker_pays) / 1_000_000
                        elif isinstance(taker_gets, dict) and taker_gets.get("currency") == "XRP":
                            amount_xrp = float(taker_gets.get("value", 0))
                        elif isinstance(taker_pays, dict) and taker_pays.get("currency") == "XRP":
                            amount_xrp = float(taker_pays.get("value", 0))

                        if amount_xrp >= min_xrp:
                            whales.append({
                                "amount": amount_xrp,
                                "from": counterparty,
                                "to": "DEX",
                                "hash": tx.get("hash"),
                                "ledger_index": idx,
                                "type": "OfferExecute"
                            })

        await asyncio.sleep(0.3)  # polite rate limit

    # Update whale cache
    if whales:
        recent_whales_cache.extend(whales)
        recent_whales_cache = recent_whales_cache[-MAX_WHALE_CACHE:]
    else:
        print("No new whale transactions found.")

    # Update last processed ledger
    last_ledger_index = latest_index

    return whales


# --- Classify the whale transaction direction ---
def classify_whale_tx(tx):
    """
    Determines the type of whale movement.
    For Payments: inflow/outflow to exchange or unknown.
    For DEX trades: indicates whether XRP was offered or received.
    """
    tx_type = tx.get("type", "Payment")
    
    if tx_type == "Payment":
        from_ex = get_exchange_by_address(tx["from"])
        to_ex = get_exchange_by_address(tx["to"])

        if to_ex:
            return "Exchange Inflow", to_ex, "🚨🚨🚨"
        elif from_ex:
            return "Exchange Outflow", from_ex, "🟢🟢🟢"
        elif from_ex and to_ex:
            return "Exchange Transfer", f"{from_ex} → {to_ex}", "🔄"
        else:
            return "Unknown Transfer", None, "💡"

    elif tx_type == "OfferCreate":
        direction = tx.get("direction", "Unknown")
        return f"DEX Trade ({direction})", "DEX", "⚡⚡⚡"

    return "Unknown", None, "💡"


# --- Format the whale alert ---
def format_whale_alert(tx, xrp_price=None):
    """
    Formats the alert message for Telegram, showing type, amount, USD value, and link.
    """
    
    classification, entity, emoji = classify_whale_tx(tx)
    usd_value = tx["amount"] * xrp_price if xrp_price else 0

    msg = (
        f"{emoji} *XRP Whale Alert* {emoji}\n\n"
        f"*Amount*: {tx['amount']:,} XRP (~${usd_value:,.2f})\n"
        f"*From*: `{tx['from']}`\n"
        f"*To*: `{tx['to']}`\n"
        f"*Type*: 🔎 *{classification}*"
    )

    if entity:
        msg += f" ({entity})"

    msg += f"\n[View Tx](https://xrpscan.com/tx/{tx['hash']})"

    return msg
