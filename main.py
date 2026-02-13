from fastapi import FastAPI, Request
from telegram import Update
from bot import create_application
from core.alerts import start_scheduler
from config import logger, WEBHOOK_PATH, PAYPAL_CLIENT_ID, PAYPAL_SECRET, PAYPAL_MODE, PAYPAL_WEBHOOK_ID
from paypal.client import PayPalClient
import os
import asyncio
from core.db import db, User_Query

application = create_application()

# Initialize PayPal client (used for webhook signature verification)
paypal_client = PayPalClient(PAYPAL_CLIENT_ID, PAYPAL_SECRET, sandbox=(PAYPAL_MODE == "sandbox"))

app = FastAPI()

# --------------------------
# PayPal webhook
# --------------------------
@app.post("/paypal/webhook")
async def paypal_webhook(request: Request):
    # Extract PayPal transmission headers
    headers = request.headers
    transmission_id = headers.get("PAYPAL-TRANSMISSION-ID")
    transmission_time = headers.get("PAYPAL-TRANSMISSION-TIME")
    cert_url = headers.get("PAYPAL-CERT-URL")
    auth_algo = headers.get("PAYPAL-AUTH-ALGO")
    transmission_sig = headers.get("PAYPAL-TRANSMISSION-SIG")

    if not PAYPAL_WEBHOOK_ID:
        logger.error("PAYPAL_WEBHOOK_ID is not configured")
        return {"ok": False, "error": "webhook_id_not_configured"}

    event = await request.json()

    try:
        verified = paypal_client.verify_webhook_signature(
            transmission_id=transmission_id,
            transmission_time=transmission_time,
            cert_url=cert_url,
            auth_algo=auth_algo,
            transmission_sig=transmission_sig,
            webhook_id=PAYPAL_WEBHOOK_ID,
            webhook_event=event,
        )
    except Exception as e:
        logger.error(f"Error verifying PayPal webhook signature: {e}")
        return {"ok": False, "error": "verification_failed"}

    if not verified:
        logger.warning("PayPal webhook signature verification failed")
        return {"ok": False, "error": "invalid_signature"}

    # Process event
    event_type = event.get("event_type")
    resource = event.get("resource", {})

    # Try to extract subscription id from resource
    subscription_id = resource.get("id") or resource.get("subscription_id") or resource.get("billing_agreement_id")

    if subscription_id:
        user = db.get(User_Query.paypal_sub_id == subscription_id)
        if user:
            user_id = user["user_id"]
            # Handle subscription lifecycle events
            if event_type in ("BILLING.SUBSCRIPTION.ACTIVATED", "BILLING.SUBSCRIPTION.UPDATED"):
                db.update({"paypal_status": True, "plan": "premium"}, User_Query.user_id == user_id)
                await application.bot.send_message(chat_id=user_id, text="📢 Your PayPal subscription is active. Thank you!")
            elif event_type in ("BILLING.SUBSCRIPTION.CANCELLED", "BILLING.SUBSCRIPTION.SUSPENDED", "BILLING.SUBSCRIPTION.EXPIRED"):
                db.update({"paypal_status": False, "plan": "free"}, User_Query.user_id == user_id)
                await application.bot.send_message(chat_id=user_id, text=("📢 Your PayPal subscription is no longer active. "
                                                                          "Manage your subscription here: https://www.paypal.com/myaccount/autopay/"))
    else:
        # Handle other events like payments that may reference billing agreement id
        if event_type == "PAYMENT.SALE.COMPLETED":
            billing_agreement_id = resource.get("billing_agreement_id")
            if billing_agreement_id:
                user = db.get(User_Query.paypal_sub_id == billing_agreement_id)
                if user:
                    user_id = user["user_id"]
                    db.update({"paypal_status": True, "plan": "premium"}, User_Query.user_id == user_id)
                    await application.bot.send_message(chat_id=user_id, text="📢 Payment received. Subscription active.")

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