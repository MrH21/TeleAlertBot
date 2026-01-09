# alerts.py
from config import logger
from core.db import db, User_Query
from core.utilities import fetch_current_price, get_candles, get_plan, calculate_price_change, TICKERS
from indicators.data_processing import process_indicators, create_price_chart_with_levels
import pandas as pd
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Proper scheduler instantiation
scheduler = AsyncIOScheduler()

# Initialize cache
from core.cache import CachedSymbolData
cache = CachedSymbolData()

# --- Save data to db ---
def save_ticker_data_to_db(interval="1h", limit=100):
    for ticker in TICKERS:
        try:
            candles = get_candles(ticker, interval, limit)
            if not candles:
                logger.warning(f"No candle data retrieved for {ticker}. Skipping.")
                continue

            df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
            indicators = process_indicators(df)

            # Update DB
            db.update({'indicators': indicators}, User_Query.ticker == ticker)
            logger.info(f"Saved indicators for {ticker} to DB.")
        except Exception as e:
            logger.error(f"Error saving ticker data for {ticker}: {e}")

# --- Check all the alerts in the DB ---
async def check_all_alerts(app):
    all_records = db.all()
    print(f"Checking {len(all_records)} record(s)...")
    
    if not all_records:
        return

    price_cache = {}
    now = pd.Timestamp.now()

    for user_record in all_records:
        user_id = user_record.get('user_id')
        alerts = user_record.get('alerts', [])
        logger.info(f"User {user_id} has {len(alerts)} alert(s).")
        alerts_to_remove = [] # collect alerts to remove after processing
        for alert in list(alerts):  # list() to allow safe removal
            try:
                if not isinstance(alert, dict):
                    logger.debug(f"SKIPPING non-dict alert: {alert} (type: {type(alert)})")
                    continue

                symbol = alert.get('ticker')
                price_target = alert.get('target')
                direction = alert.get('direction')
                last_checked = alert.get('last_checked')            

                if not symbol or price_target is None or direction not in ["above", "below"]:
                    logger.info(f"SKIPPING: Skipping invalid alert for user {user_id} on symbol {symbol}")
                    continue
                    
                # Determine user plan and interval
                plan = await get_plan(user_record)
                interval = 60 if plan == "premium" else 360
                
                # Skip if not time to check yet
                if last_checked and (now - pd.Timestamp(last_checked)).total_seconds() < interval:
                    continue

                # Fetch price once per symbol
                if symbol not in price_cache:
                    price_cache[symbol] = await fetch_current_price(symbol)
                    
                current_price = price_cache[symbol]
                
                if current_price is None:
                    continue

                # Check alert condition
                hit = current_price >= price_target if direction == "above" else current_price <= price_target
                
                # Get percentage change
                try:
                    candles = get_candles(symbol, "1h", 2)

                    if len(candles) < 2:
                        raise ValueError(f"Not enough candles returned for XRPUSDT: {candles}")

                    prev_price = float(candles[0][3])
                    last_price = float(candles[1][3])

                    price_change = calculate_price_change(prev_price, last_price)  # old_price is fetched inside the function
                    if price_change is None:
                        change_str = "percentage change n/a"
                    elif price_change > 0:
                        change_str = f"↗ {price_change:.2f}% change (1hr)"
                    elif price_change < 0:
                        change_str = f"↘ {abs(price_change):.2f}% change (1hr)"
                    else:
                        change_str = "↔ 0.00%"

                except Exception as e:
                    logger.error(f"Error calculating price change for {symbol}: {e}")
                    
                if hit:
                    # Send alert
                    await app.bot.send_message(
                        chat_id=user_id,
                        text=(
                            f"💥💥💥 *TARGET ALERT!* 💥💥💥\n"
                            "*Your price target has been hit!*\n\n"
                            f"*{symbol}* is now *{current_price:,.4f}*, \n"                            
                            f" (*{direction} {price_target:,.4f}*)\n"
                            f"{change_str}\n\n"
                            f"_(This alert has been deleted)_"
                        )
                        ,parse_mode='Markdown'
                    )
                    alerts_to_remove.append(alert)  # Mark for removal
                else:
                    # Update last checked for interval calculation
                    alert['last_checked'] = now.strftime('%Y-%m-%dT%H:%M:%S.%f%z')
                                    
            except Exception as e:
                logger.error(f"Error processing alert {alert}: {e}")                
                        
        # Remove alerts after processing
        for alert in alerts_to_remove:
            user_record['alerts'].remove(alert)
        # Update DB once per user
        db.update({'alerts': user_record['alerts']}, User_Query.user_id == user_id)
        
# --- Start the scheduler ---
async def start_scheduler(app, global_tick=60):
    """
    Start the global scheduler for checking alerts.
    `app` must be provided to send messages.
    `global_tick` sets how often the scheduler triggers check_all_alerts.
    """
    try:     
        if not app:
            logger.warning("Scheduler not started: no app provided.")
            return
        
        # Ensure event loop is running
        await asyncio.sleep(0)  # Yield control to ensure the loop is ready

        # Remove previous jobs
        scheduler.remove_all_jobs()
        
        loop = asyncio.get_running_loop()
        
        # Alert checking job
        def job_func_check_alerts():
            asyncio.run_coroutine_threadsafe(check_all_alerts(app), loop)
            
        # Add job
        scheduler.add_job(
            func=job_func_check_alerts,
            trigger='interval',
            seconds=global_tick,
            id='global_check_alerts',
            replace_existing=True
        )

        # Cache saving job - saves processed indicator data every hour
        async def run_hourly_cache_update(app):
            for symbol in TICKERS:  # Your symbol list
                    try:
                        # process_indicators and create_price_chart_with_levels are sync/blocking
                        # run them in a thread to avoid awaiting a non-coroutine
                        await asyncio.to_thread(cache.save_data, symbol, process_indicators, create_price_chart_with_levels)
                    except Exception as e:
                        logger.error(f"Error caching {symbol}: {e}")

        def job_func_cache():
            asyncio.run_coroutine_threadsafe(run_hourly_cache_update(app), loop)

        scheduler.add_job(
            func=job_func_cache,
            trigger='interval',
            seconds=3600,  # every hour
            id='hourly_cached_symbol_data',
            replace_existing=True
        )

        if not scheduler.running:
            scheduler.start()
            logger.info("Scheduler started with global alert checker and cache job.")
        else:
            logger.info("Scheduler already running; job updated.")
    except Exception as e:
        logger.error(f"Error starting scheduler: {e}")
        