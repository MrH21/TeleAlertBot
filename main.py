from fastapi import FastAPI, Request
from telegram import Update
from bot import create_application
from config import WEBHOOK_URL
from contextlib import asynccontextmanager

application = create_application()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    await application.bot.set_webhook(WEBHOOK_URL)
    print(f"Webhook set to: {WEBHOOK_URL}")
    yield
    # shutdown
    await application.shutdown()
    
app = FastAPI(lifespan=lifespan)

@app.post("/webhook")
async def telegram_webhook(requst: Request):
    data = await requst.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return {"ok":True}

