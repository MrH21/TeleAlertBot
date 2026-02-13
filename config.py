import os
import logging
from dotenv import load_dotenv

# Load .env file if present (helps local development)
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_PATH = "/telegram_webhook" #Telegram webhook
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
PAYPAL_SECRET = os.getenv("PAYPAL_SECRET")
PAYPAL_MODE = os.getenv("PAYPAL_MODE", "sandbox")
PAYPAL_PLAN_ID = os.getenv("PAYPAL_PLAN_ID")
PAYPAL_WEBHOOK_ID = os.getenv("PAYPAL_WEBHOOK_ID")

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
