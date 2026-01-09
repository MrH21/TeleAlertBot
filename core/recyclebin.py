# Whale alerts ---------------------------------
"""
Alerts.py

    try: 
        whale_cache = await get_whale_txs(min_xrp=500_000)
        # Update global cache        
        if whale_cache:
            global recent_whales_cache, user_sent_whales
            update_recent_whales(whale_cache)
            recent_whales_cache = recent_whales_cache[-MAX_WHALE_CACHE:]
            print(f"Found {len(whale_cache)} new whale transaction(s) from running scheduler.")
        else:
            print("No new whale transactions found from running scheduler.")
    except Exception as e:
        logger.error(f"Error fetching whale transactions: {e}")
        whale_cache = []
            
    for user_record in all_records:
        user_id = user_record.get('user_id')
        plan = await get_plan(user_record)
        current_price = await fetch_current_price("XRPUSDT")
        
        sent_hashes = user_sent_whales.setdefault(user_id, set())
        
        # Whale alerts
        if user_record.get("watch_status") and recent_whales_cache:
            for tx in recent_whales_cache:
                if tx["hash"] in sent_hashes:
                    continue
                msg = format_whale_alert(tx, current_price)
                try:
                    await app.bot.send_message(
                        chat_id=user_id,
                        text=msg,
                        parse_mode="Markdown"
                    )
                    sent_hashes.add(tx["hash"])
                except Exception as e:
                    logger.error(f"Error sending whale alert to {user_id}: {e}")


Handlers.py

# --- Whale transaction watcher ---
async def xrpnet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = db.get(User_Query.user_id == user_id)
    
    if not user:
        await update.message.reply_text("❌ Please use /start first.")
        return
    
    plan = await get_plan(user)
    
    message = await get_xrp_health()  # Ensure connection to XRPL server
    await update.message.reply_text(f"{message}", parse_mode="Markdown")  
        
    # Take the last 5 whale transactions
    preview = recent_whales_cache[-5:]

    #logger.info(f"Recent whale cache for user {user_id}: {preview} on whales command")
    
    keyboard = [
        [InlineKeyboardButton("✅ Enable XRP Alerts", callback_data="whale_on")],
        [InlineKeyboardButton("❌ Disable XRP Alerts", callback_data="whale_off")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if not preview:
        await update.message.reply_text(
            "🐋 RECENT WHALE TRANSACTIONS\n\n_No recent whale transactions found at the moment_", 
            parse_mode="Markdown", 
            reply_markup=reply_markup
        )
        return
    
    # Format messages
    xrp_price = await fetch_current_price("XRPUSDT")
    msgs = [format_whale_alert(tx, xrp_price) for tx in preview]
    header = f"🐋 *RECENT WHALE TRANSACTIONS*\n\n"
   
    full_msg = header + "\n\n".join(msgs)
    
    if plan == "premium":
        await update.message.reply_text(full_msg, parse_mode="Markdown", reply_markup=reply_markup)
    else:  # Free plan
        notice = "💡 You are currently on the *Free* plan. To get whale alerts /upgrade"
        await update.message.reply_text(notice, parse_mode="Markdown")


# --- Whale button handler ----
async def whale_button_handler(update: Update, context:CallbackContext):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    user = db.get(User_Query.user_id == user_id)
    
    if not user:
        await update.message.reply_text("❌ Please use /start first.")
        return
    
    if query.data == "whale_on":
        db.update({"watch_status": True}, User_Query.user_id == user_id)
        await query.edit_message_text("✅ Whale alerts enabled")
    elif query.data == "whale_off":
        db.update({"watch_status": False}, User_Query.user_id == user_id)
        await query.edit_message_text("❌ Whale alerts disabled.")



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

        await asyncio.sleep(0.2)  # polite rate limit

    # Update whale cache
    if whales:
        recent_whales_cache.extend(whales)
        recent_whales_cache = recent_whales_cache[-MAX_WHALE_CACHE:]
    else:
        print("No new whale transactions found.")

    # Update last processed ledger
    last_ledger_index = latest_index

    return whales

Xrp Functions.py
# --- Classify the whale transaction direction ---
def classify_whale_tx(tx):

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



"""