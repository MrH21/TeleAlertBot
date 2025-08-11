from telegram.ext import Application, CommandHandler
from core.handlers import start, setticker, settarget, myticker, myalert, help_command, confirm_or_set_ticker
from config import BOT_TOKEN
from telegram.ext import CommandHandler, MessageHandler, filters, ConversationHandler
from core.state import CONFIRM_TICKER_CHANGE

def create_application():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    # handle the ticker selection
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('setticker', setticker)],
        states={
            CONFIRM_TICKER_CHANGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_or_set_ticker)],
        },
        fallbacks=[],
    )
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("settarget", settarget))
    app.add_handler(CommandHandler("myticker", myticker))
    app.add_handler(CommandHandler("myalert", myalert))
    app.add_handler(CommandHandler("help", help_command))

    return app
   