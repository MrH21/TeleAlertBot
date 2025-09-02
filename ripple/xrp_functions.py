import pandas as pd
from config import logger
from core.cache import recent_whales_cache, MAX_WHALE_CACHE
from ripple.wallets_data import wallets
from tinydb import TinyDB, Query
import asyncio
import aiohttp
from datetime import datetime, timezone
import requests
from xrpl.asyncio.clients import AsyncJsonRpcClient, AsyncWebsocketClient
from xrpl.models.requests import Ledger, ServerInfo, AccountObjects

# --- Set up wallet database ---
wdb = TinyDB("exchange_wallets.json")
wallets_table = wdb.table("wallets")

# --- Set up tinydby if no wallet data ---
if len(wallets_table) == 0:
    wallets_table.insert_multiple(wallets)

# -- XRP Ledger Client and global ledger tracker ---
last_ledger_index = None
client = AsyncJsonRpcClient("https://s2.ripple.com:51234/")

# --- Extract XRP health from server info ---
async def get_xrp_health():
    try:
        query_response = await client.request(ServerInfo())
        server_info = query_response.result
        print(server_info)
        info = server_info["info"]
        validated_ledger = info["validated_ledger"]
        cache = info["cache"]
    except Exception as e:
        logger.error(f"XRP health error {e}")
    
    message = f"🔋 *XRP Ledger Health:*\n\n"
        
    # Ledger info
    # Ledger Age indicator
    age = validated_ledger['age']
    if age <= 5:
        age_status = "✅"
    elif age <= 10:
        age_status = "⚠️"
    else:
        age_status = "❌"

    # Base Fee indicator
    fee = validated_ledger['base_fee_xrp']
    if fee <= 0.0001:
        fee_status = "✅"
    elif fee <= 0.001:
        fee_status = "⚠️"
    else:
        fee_status = "❌"
    
    message += f"🔹 *Ledger Info* \n"
    message += f"- Ledger Index: {validated_ledger['seq']} ~ _latest validated ledger_\n"
    message += f"- Ledger Age: {validated_ledger['age']} sec {age_status} ~ _seconds since last ledger closed_\n"
    message += f"- Base Fee: {validated_ledger['base_fee_xrp']} {fee_status} ~ _minimum XRP required_\n\n"
    
    # Cache info
    message += f"💾 *Cache*\n"
    message += f"- Size: {cache['size']}\n"
    message += f"- Enabled: {cache['is_enabled']}\n"
    message += f"- Full: {cache['is_full']}\n\n"

    # Network info
    message += f"🌐 *Network*\n"
    message += f"- Validation Quorum: {info['validation_quorum']}\n"
    message += f"- Uptime: {info['uptime']} sec\n"
    message += f"- Rippled Version: {info['rippled_version']}\n"

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
            #print(f"Ledger {idx} fetched with {len(txs)} transactions")
            
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

# --- Obtain Escrow information ---

RIPPLE_ESCROW_ACCOUNTS = [
    "rMp7Vjb52z7xvef96dgE6FQVfcJp2tE2f2",
    "rPVMhWBsfF9iMXYj3aAzJVkPDTFNSyWdKy",
    "rHb9CJAWyB4rj91VRWn96DkukG4bwdtyTh",
    "rKVEGLiv4JgBDG3y62zXkWc6sYJ5kVh3z",
    "rELeasERs3m4inA1UinRLTpXemqyStqzwh"
    
]
escrow_db = TinyDB("escrow_data.json")

def get_monthly_escrow_summary():
    total_locked = 0
    escrow_details = []

    # Iterate over all known accounts
    for account in RIPPLE_ESCROW_ACCOUNTS:
        url = f"https://api.xrpscan.com/api/v1/account/{account}/escrows"
        resp = requests.get(url)
        if resp.status_code != 200:
            continue
        data = resp.json()

        for e in data:
            amount = int(e["Amount"]) / 1_000_000  # drops → XRP
            total_locked += amount

            # Convert FinishAfter (Ripple epoch) to datetime
            finish_after = e.get("FinishAfter")
            if finish_after:
                finish_date = datetime.datetime(2000, 1, 1) + datetime.timedelta(seconds=int(finish_after))
                finish_str = finish_date.strftime("%Y-%m-%d")
            else:
                finish_str = "N/A"

            escrow_details.append({
                "account": e["Account"],
                "amount": amount,
                "release_date": finish_str
            })

    # Determine current month
    now = datetime.now(timezone.utc)
    month_key = now.strftime("%Y-%m")

    Entry = Query()
    last_record = escrow_db.get(Entry.month == month_key)

    if not last_record:
        # First snapshot for the month
        escrow_db.insert({
            "month": month_key,
            "total_locked": total_locked,
            "released": 0,
            "re_escrowed": 0
        })
        released = 0
        re_escrowed = 0
    else:
        prev_total = last_record["total_locked"]
        # Estimate released & re-escrowed
        released = max(prev_total - total_locked, 0)
        re_escrowed = max(total_locked - (prev_total - released), 0)
        # Update record
        escrow_db.update({
            "total_locked": total_locked,
            "released": released,
            "re_escrowed": re_escrowed
        }, Entry.month == month_key)

    # Build summary message
    message = f"📊 XRP Escrow Update ({month_key})\n\n"
    message += f"🔒 Total Locked: {total_locked:,.0f} XRP\n"
    message += f"📤 Released: {released:,.0f} XRP\n"
    message += f"🔁 Re-escrowed: {re_escrowed:,.0f} XRP\n"
    message += f"📈 Net Circulation Change: {released - re_escrowed:,.0f} XRP\n\n"

    # Show top escrows (first 10 for brevity)
    for e in escrow_details[:10]:
        message += f"- {e['amount']:,.0f} XRP from {e['account']}, release: {e['release_date']}\n"

    return message