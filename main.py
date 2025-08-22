from fastapi import FastAPI, Request
from telegram import Update, Bot
from bot import create_application
from core.alerts import start_scheduler
from config import WEBHOOK_URL, WEBHOOK_PATH, logger
import os
from core.db import db, User_Query
from telegram.ext import Application, ContextTypes
from core.scheduler import start_msg_scheduler

application = create_application()

app = FastAPI()

# Retrieve the secret key from environment variables
SIGNING_SECRET = os.getenv("LS_WEBHOOK_SECRET")
if not SIGNING_SECRET:
    raise ValueError("LS_WEBHOOK_SECRET environment variable not set")

@app.post("/lemonsqueezy/webhook")
async def lemon_webhook(request: Request):
    payload = await request.json()
    print("Webhook payload:", payload)  # For testing
    
    event = payload.get("event")
    meta = payload.get("meta", {})
    telegram_id = meta.get("telegram_id")
    data_attrs = payload.get("data", {}).get("attributes", {})
    plan_version = f"{data_attrs.get('product_name')} - {data_attrs.get('variant_name')}"
    
    telegram_id = payload.get('data', {}).get('attributes', {}).get('custom', {}).get('telegram_id') \
              or payload.get('meta', {}).get('telegram_id')

    billing_url = f"https://lupox.lemonsqueezy.com/billing?telegram_id={telegram_id}"
    
    if not telegram_id:
        logger.error("Telegram ID not found in webhook payload.")
        return {"ok": False, "error": "Telegram ID not found"}
    
    User = User_Query()
    telegram_id = int(telegram_id)  # ensure same type as in DB
    if event in ["subscription_created", "subscription_updated", "subscription_renewed", "subscription_resumed"]:
        db.update({"plan": "premium", "subscriber": True}, User.telegram_id == telegram_id)
        # Optional: send Telegram confirmation
        await app.send_message(chat_id=telegram_id, text=f"📢 Subscription Active ✅ Plan: {plan_version}")
    elif event in ["subscription_cancelled", "subscription_expired", "payment_failed"]:
        db.update({"plan":"free", "subscriber": False}, User.telegram_id == telegram_id)
        await app.send_message(chat_id=telegram_id, text=f"📢 Subscription Inactive ❌\nManage your subscription here: <a href=\"{billing_url}\"><b>Manage Subscription</b></a>")


    return {"ok": True}


@app.post("/telegram_webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return {"ok": True}

@app.on_event("startup")
async def startup_event():
    await application.initialize()
    await start_scheduler(application)
    #start_msg_scheduler(application)  # Start the message scheduler in the background