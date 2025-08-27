import os
import logging

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
