from fastapi import FastAPI, Request
from telegram import Update
from bot import create_application
from config import WEBHOOK_URL, WEBHOOK_PATH
from contextlib import asynccontextmanager

application = create_application()

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

