import pandas as pd
from config import logger
from core.cache import recent_whales_cache, MAX_WHALE_CACHE
from ripple.wallets_data import wallets
from tinydb import TinyDB, Query
import asyncio
import numpy as np
import requests
from sklearn.cluster import MiniBatchKMeans
from xrpl.asyncio.clients import AsyncJsonRpcClient
from xrpl.models.requests import Ledger, ServerInfo

# --- Binance url ---
BINANCE_URL = "https://api.binance.com/api/v3/klines"

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
def classify_activity(age: int, fee: float, active: int, new: int):
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
    # TPS
    '''if tps > 20:
        tps_label, tps_emoji = "High", "🚀"
    elif tps > 5:
        tps_label, tps_emoji = "Medium", "⚡"
    else:
        tps_label, tps_emoji = "Low", "💤"'''

    # Active addresses
    if active > 2000:
        active_label, active_emoji = "High", "🌋"
    elif active > 500:
        active_label, active_emoji = "Medium", "🔥"
    else:
        active_label, active_emoji = "Low", "🌱"

    # New addresses
    if new > 200:
        new_label, new_emoji = "High", "✨"
    elif new > 50:
        new_label, new_emoji = "Medium", "🌟"
    else:
        new_label, new_emoji = "Low", "🔹"

    return {
        "age": (age_label, age_emoji),
        "fee": (fee_label, fee_emoji),
        #"tps": (tps_label, tps_emoji),
        "active": (active_label, active_emoji),
        "new": (new_label, new_emoji),
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
        # --- Initialize counters ---
        tx_total = 0
        active_addrs, new_addrs = set(), set()
        
        '''
        # --- Loop over recent ledgers ---
        for idx in range(latest_index - lookback_ledgers + 1, latest_index + 1):
            ledger_resp = await client.request(Ledger(ledger_index=idx, transactions=True, expand=True))
            txs = ledger_resp.result.get("ledger", {}).get("transactions", [])
            tx_total += len(txs)

            for tx in txs:
                tx_json = tx.get("tx_json", {})
                if "Account" in tx_json:
                    active_addrs.add(tx_json["Account"])
                if tx_json.get("TransactionType") == "Payment" and "Destination" in tx_json:
                    active_addrs.add(tx_json["Destination"])

                for node in tx.get("meta", {}).get("AffectedNodes", []):
                    created = node.get("CreatedNode")
                    if created and created.get("LedgerEntryType") == "AccountRoot":
                        new_addrs.add(created["NewFields"]["Account"])

            await asyncio.sleep(0.1)  # throttle to avoid overloading node

        # --- TPS estimate ---
        tps_est = tx_total / (lookback_ledgers * 4)  # approx 4s per ledger

        # --- Classify activity levels ---
        activity = classify_activity(
            age=validated_ledger["age"],
            fee=validated_ledger["base_fee_xrp"],
            tps=tps_est,
            active=len(active_addrs),
            new=len(new_addrs)
        )'''
        
        activity = classify_activity(
            age=validated_ledger["age"],
            fee=validated_ledger["base_fee_xrp"],
            active=len(active_addrs),
            new=len(new_addrs)
        )
        # --- Build message ---
        message = f"🔋 *XRP Ledger Health:*\n\n"
        message += f"🔹 *Ledger Info* \n"
        message += f"- Ledger Index: {validated_ledger['seq']}\n"
        message += f"- Ledger Age: {validated_ledger['age']} sec {activity['age']}\n"
        message += f"- Transactions {txs}\n"
        message += f"- Base Fee: {validated_ledger['base_fee_xrp']} {activity['fee']}\n\n"        
        
        message += f"🌐 *Network*\n"
        #message += f"- TPS: {tps_est:.2f} → {activity['tps'][1]} *{activity['tps'][0]}*\n"
        #message += f"- Active Addresses: {len(active_addrs)} → {activity['active'][1]} *{activity['active'][0]}*\n"
        #message += f"- New Addresses: {len(new_addrs)} → {activity['new'][1]} *{activity['new'][0]}*\n"
        message += f"- Validation Quorum: {info['validation_quorum']}\n"
        message += f"- Rippled Version: {info['rippled_version']}\n\n"

    except Exception as e:
        logger.error(f"XRP health error: {e}")

    return message

# --- Getting the support and resistance levels ---
def get_candles(symbol="XRPUSDT", interval="1d", limit=500):
    url = f"{BINANCE_URL}?symbol={symbol}&interval={interval}&limit={limit}"
    data = requests.get(url).json()
    if not isinstance(data, list):
        raise ValueError(f"Unexpected API Response: {data}")
    # each kline
    candles = []
    for c in data:
        try:
            high = float(c[2])
            low = float(c[3])
            close = float(c[4])
            volume = float(c[5])
            
            candles.append((high,low,close,volume))
        except ValueError:
            continue
    return candles

def get_key_levels(symbol="XRPUSDT", interval="1d", clusters=6):
    candles = get_candles(symbol,interval)
    latest_close = candles[-1][2]  # last candle's close price
    
    prices = []
    weights = []
    VOLUME_SCALE = 50_000_000
    
    for h, l, c, v in candles:
        prices.extend([h, l])
        weight = np.log1p(v / VOLUME_SCALE)
        weights.extend([weight, weight]) # weighting for h and l by volume
        
    prices = np.array(prices).reshape(-1,1)
    weights = np.array(weights)
    
    # run MiniBatchKMeans
    kmeans = MiniBatchKMeans(n_clusters=clusters, random_state=0, n_init=10,batch_size=256)
    kmeans.fit(prices,sample_weight=weights)
    
    levels = sorted(kmeans.cluster_centers_.flatten())
    levels = [round(l, 4) for l in levels]
    
    # Split into support/resistance based on latest close
    support = [lvl for lvl in levels if lvl < latest_close]
    resistance = [lvl for lvl in levels if lvl > latest_close]

    return latest_close, support, resistance


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

