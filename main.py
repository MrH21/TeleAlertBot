from fastapi import FastAPI, Request
from telegram import Update
from bot import create_application
from core.alerts import start_scheduler
from config import WEBHOOK_URL, WEBHOOK_PATH

application = create_application()

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    # Initialize the Telegram app
    await application.initialize()

    # Start the alert scheduler
    await start_scheduler(application)

    # Set webhook if needed
    current = await application.bot.get_webhook_info()
    if current.url != WEBHOOK_URL:
        await application.bot.set_webhook(WEBHOOK_URL)
        print(f"Webhook set to: {WEBHOOK_URL}")
    else:
        print(f"Webhook already set to: {WEBHOOK_URL}")

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return {"ok": True}
