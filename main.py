from fastapi import FastAPI, Request
from telegram import Update
from bot import create_application
from config import WEBHOOK_URL, WEBHOOK_PATH
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from core.db import db, User_Query
from config import logger
from core.utilities import check_target, get_plan

application = create_application()
scheduler = AsyncIOScheduler

# --- Scheduled Alert ---   
async def scheduled_alert(app):
    users_with_targets = db.search((User_Query.target != None) & (User_Query.direction != None))
    logger.info(f"Found {len(users_with_targets)} users with targets")
    
    for record in users_with_targets:
        user_id = record['user_id']
        symbol = record.get('ticker')
        direction = record.get('direction')

        if not symbol:
            logger.warning(f"No symbol set for user {user_id}")
            continue
        
        close, hit, date = await check_target(user_id, symbol)
        
        if close is None:
            continue  # Skip users with invalid data
        
        if hit:
            msg = (
                f"📢 *PRICE ALERT!*\n"
                f"✅ Target hit: {symbol} went {direction} ${record['target']:,.4f} on {date}\n\n"
                f"The target has been cleared, please set new.\n\n"
                f"📌 Want more alerts and interval options? Pro version coming soon!"
            )
            logger.info(f"🎯 Target hit for user {user_id}")
            db.update({'target':None, 'direction':None}, User_Query.user_id == user_id)
            await app.bot.send_message(chat_id=user_id, text=msg, parse_mode='Markdown')
        else:
            logger.info(f"No target hit.")

# --- Starting the scheduler ---
async def start_scheduler(app, user):
    plan = await get_plan(user)
    interval = 60 if plan == "premium" else 120
    scheduler.add_job(scheduled_alert, 'interval', args=[app], seconds=interval)
    scheduler.start()
    logger.info("Premium Plan: Scheduler has started")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    await application.initialize()
    # only set webhook if different or missing
    current = await application.bot.get_webhook_info()
    if current.url != WEBHOOK_URL:
        await application.bot.set_webhook(WEBHOOK_URL)
        print(f"Webhook set to: {WEBHOOK_URL}")
    else:
        print(f"Webhook already set to: {WEBHOOK_URL}")
    yield
    print("Shutdown: leaving webhook active for cold start wakeup.")
    
app = FastAPI(lifespan=lifespan)

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return {"ok":True}

