from telegram import LabeledPrice, Update
from telegram.ext import ContextTypes
from core.handlers import db, User_Query
from config import logger

async def send_upgrade_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    prices = [LabeledPrice(label="Premium Plan Upgrade", amount=1275)] # Price in cents (e.g., $12.75)
    print(f"Sending upgrade invoice to user {user_id} with prices: {prices}")
    try:
        await update.message.reply_invoice(
            title="Upgrade to Premium",
            description="Upgrade to the PREMIUM plan for more alerts and features.",
            payload="upgrade_premium",
            provider_token="335f4e537376db1f7eae2af8b842b15f09e2aeed:qwerty",
            currency="USD",
            prices=prices
        )
    except Exception as e:
        logger.error(f"Error with sending upgrade invoice: {e}")
        
    
async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)
    
async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db.update({"plan": "premium"}, User_Query.user_id == user_id)
    await update.message.reply_text("🎉 Payment successful! You are now on the PREMIUM plan.")