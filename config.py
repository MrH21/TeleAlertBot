import os
import logging
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
