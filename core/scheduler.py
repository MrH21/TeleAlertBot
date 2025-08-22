from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timezone
from telegram import Bot
from core.db import db, User_Query

MAX_DAYS = 3

async def send_trial_expiry_message(bot:Bot):
    users = db.all()
    now = datetime.now(timezone.utc)
    
    for user in users:
        trial_expiry_str = user.get('trial_expiry')
        user_id = user.get('user_id')
        if not trial_expiry_str or not user_id:
            continue
        
        if user.get("trial_message_sent"):
            continue
        
        trial_expiry = datetime.fromisoformat(trial_expiry_str)
        days_left = (trial_expiry - now).days
        
        if days_left <= MAX_DAYS:
            checkout_url = f"https://lupox.lemonsqueezy.com/checkout?telegram_id={user_id}"
            msg = f"Your trial ends soon. Please <a href=\"{checkout_url}\"><b>Subscribe</b></a> to continue using premium features."
            await bot.send_message(
                chat_id=user_id,
                text=msg,
                disable_web_page_preview=True
            )
            # mark as sent
            db.update(
                User_Query.user_id == user_id,
                {"trial_message_sent": True}
            )
            
            
async def start_msg_scheduler(bot: Bot):
    scheduler = AsyncIOScheduler()
    # Run daily at 9:00 UTC
    scheduler.add_job(send_trial_expiry_message, 'cron', hour=9, args=[bot])
    scheduler.start()