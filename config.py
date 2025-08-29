import os
import logging

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_EXT = "/telegram_webhook"
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_PATH = f"/{WEBHOOK_URL}{WEBHOOK_EXT}"
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
