import os
import logging

BOT_TOKEN = os.getenv("BOT_TOKEN")
#BOT_TOKEN = "8436169622:AAFxmzXV3u5MPU5m5ucV36nY2JiTCe9a66I"
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
