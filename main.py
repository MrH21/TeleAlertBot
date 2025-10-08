from fastapi import FastAPI, Request
from telegram import Update
from bot import create_application
from core.alerts import start_scheduler
from config import logger, WEBHOOK_PATH
import os
import asyncio
from core.db import db, User_Query

application = create_application()

app = FastAPI()

# Retrieve the secret key from environment variables
SIGNING_SECRET = os.getenv("WC_WEBHOOK_SECRET")
if not SIGNING_SECRET:
    raise ValueError("WC_WEBHOOK_SECRET environment variable not set")

@app.post("/woocommerce/webhook")
async def woo_webhook(request: Request):
    # Optional secret validation
    secret = request.query_params.get("secret")
    if secret != SIGNING_SECRET:
        return {"ok": False, "error": "Invalid secret"}

    payload = await request.json()
    print("WooCommerce Webhook payload:", payload)  # Debugging

    # Retrieve Telegram ID (must be included in WooCommerce subscription metadata)
    telegram_id = payload.get('meta', {}).get('telegram_id')
    if not telegram_id:
        logger.error("Telegram ID not found in webhook payload.")
        return {"ok": False, "error": "Telegram ID not found"}
    
    telegram_id = int(telegram_id)
    User = User_Query()  # Your DB query class

    # Extract plan details
    line_items = payload.get('line_items', [])
    plan_name = line_items[0].get('name') if line_items else "Unknown Plan"
    billing_url = f"https://lupocreative.online/my-account/subscriptions/{payload.get('id')}"

    # Map WooCommerce subscription status to your program logic
    status = payload.get('status')
    if status in ["active", "on-hold", "pending"]:  # Treat 'on-hold' as active if you want
        db.update({"plan": "premium", "subscriber": True}, User.telegram_id == telegram_id)
        await app.send_message(
            chat_id=telegram_id,
            text=f"📢 Subscription Active ✅ Plan: {plan_name}"
        )
    elif status in ["cancelled", "expired", "failed"]:
        db.update({"plan":"free", "subscriber": False}, User.telegram_id == telegram_id)
        await app.send_message(
            chat_id=telegram_id,
            text=f"📢 Subscription Inactive ❌\nManage your subscription here: "
                 f"<a href=\"{billing_url}\"><b>Manage Subscription</b></a>"
        )

    return {"ok": True}


# --------------------------
# Telegram webhook
# --------------------------
@app.post("/telegram_webhook")
async def telegram_webhook(request: Request):
    try:    
        data = await request.json()
        update = Update.de_json(data, application.bot)
        await application.process_update(update)
        return {"ok": True}
    except Exception as e:
        logger.error(f"Error processing Telegram webhook: {e}")
        return {"ok": False, "error": str(e)}

# --------------------------
# Startup event
# --------------------------
@app.on_event("startup")
async def startup_event():
    try:
        logger.info("MAIN: Initializing Telegram application...")
        await application.initialize()
        # Launch the scheduler as a background task
        asyncio.create_task(start_scheduler(application))
        logger.info("MAIN: Scheduler started in background.")
    except Exception as e:
        logger.error(f"Error during startup: {e}")