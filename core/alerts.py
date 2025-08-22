# alerts.py
from config import logger
from core.db import db, User_Query
from core.utilities import fetch_current_price, get_plan
import pandas as pd
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Proper scheduler instantiation
scheduler = AsyncIOScheduler()

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
                    logger.info(f"SKIPPING {symbol} due to interval.")
                    continue

                # Fetch price once per symbol
                if symbol not in price_cache:
                    price_cache[symbol] = await fetch_current_price(symbol)
                    
                current_price = price_cache[symbol]
                
                if current_price is None:
                    continue

                # Check alert condition
                hit = current_price >= price_target if direction == "above" else current_price <= price_target

                logger.info(f"Checking {symbol}: price={current_price}, target={price_target}, direction={direction}, hit={hit}")
                if hit:
                    # Send alert
                    await app.bot.send_message(
                        chat_id=user_id,
                        text=(
                            f"💥💥💥 *TARGET ALERT!* 💥💥💥\n"
                            "*Your price target has been hit!*\n\n"
                            f"*{symbol}* is now *{current_price:,.4f}*\n"
                            f" (*{direction} {price_target:,.4f}*)\n\n"
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
        
        def job_func():
            asyncio.run_coroutine_threadsafe(check_all_alerts(app), loop)
            
        # Add job
        scheduler.add_job(
            func=job_func,
            trigger='interval',
            seconds=global_tick,
            id='global_check_alerts',
            replace_existing=True
        )

        if not scheduler.running:
            scheduler.start()
            logger.info("Scheduler started with global alert checker.")
        else:
            logger.info("Scheduler already running; job updated.")
    except Exception as e:
        logger.error(f"Error starting scheduler: {e}")
        