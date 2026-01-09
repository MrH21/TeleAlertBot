import pandas as pd
from config import logger
from core.cache import recent_whales_cache, MAX_WHALE_CACHE
from ripple.wallets_data import wallets
from tinydb import TinyDB, Query
import asyncio
import numpy as np
import requests

from xrpl.asyncio.clients import AsyncJsonRpcClient
from xrpl.models.requests import Ledger, ServerInfo

# --- Set up wallet database ---
wdb = TinyDB("exchange_wallets.json")
wallets_table = wdb.table("wallets")

# --- Set up tinydby if no wallet data ---
if len(wallets_table) == 0:
    wallets_table.insert_multiple(wallets)

# -- XRP Ledger Client and global ledger tracker ---
last_ledger_index = None
client = AsyncJsonRpcClient("https://s2.ripple.com:51234/")

# --- Classify Network Activity ---
def classify_activity(age: int, fee: float):
    """
    Returns emojis + labels for age, fee, TPS, active, and new addresses.
    Thresholds are arbitrary and can be tuned.
    """
    # Ledger Age indicator
    if age <= 5:
        age_label, age_emoji = "Low", "✅"
    elif age <= 10:
        age_label, age_emoji = "Medium", "⚠️"
    else:
        age_label, age_emoji = "High", "❌"

    # Base Fee indicator
    if fee <= 0.0001:
        fee_label, fee_emoji = "Low", "✅"
    elif fee <= 0.001:
        fee_label, fee_emoji = "Medium", "⚠️"
    else:
        fee_label, fee_emoji = "High", "❌"


    return {
        "age": (age_label, age_emoji),
        "fee": (fee_label, fee_emoji),
    }

# --- Extract XRP health from server info ---
async def get_xrp_health(lookback_ledgers: int = 20):
    message = "❌ Could not fetch XRP health info."  # default if something fails

    try:
        # --- Get server info ---
        resp = await client.request(ServerInfo())
        info = resp.result["info"]
        validated_ledger = info["validated_ledger"]
        latest_index = validated_ledger["seq"]
        ledger_resp = await client.request(Ledger(ledger_index=latest_index, transactions=True, expand=True))
        txs = len(ledger_resp.result.get("ledger", {}).get("transactions", []))


        # --- Classify activity levels ---
        activity = classify_activity(
            age=validated_ledger["age"],
            fee=validated_ledger["base_fee_xrp"]

        )

        # --- Build message ---
        message = f"🔋 *XRP Ledger Health:*\n\n"
        message += f"🔹 *Ledger Info* \n"
        message += f"- Ledger Index: {validated_ledger['seq']}\n"
        message += f"- Ledger Age: {validated_ledger['age']} sec {activity['age']}\n"
        message += f"- Transactions {txs}\n"
        message += f"- Base Fee: {validated_ledger['base_fee_xrp']} {activity['fee']}\n\n"        
        
        message += f"🌐 *Network*\n"
        message += f"- Validation Quorum: {info['validation_quorum']}\n"
        message += f"- Rippled Version: {info['rippled_version']}\n\n"

    except Exception as e:
        logger.error(f"XRP health error: {e}")

    return message

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
