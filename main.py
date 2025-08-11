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
    await application.bot.set_webhook(WEBHOOK_URL)
    print(f"Webhook set to: {WEBHOOK_URL}")
    yield
    # shutdown
    await application.bot.delete_webhook()
    
app = FastAPI(lifespan=lifespan)

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return {"ok":True}

