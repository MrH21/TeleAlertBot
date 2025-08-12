from telegram.ext import Application, CommandHandler
from core.handlers import start, addalert, select_ticker, select_target, select_direction, myalerts, help_command
from config import BOT_TOKEN
from telegram.ext import CommandHandler, MessageHandler, filters, ConversationHandler
from core.state import SELECTING_TICKER, SETTING_TARGET, SELECTING_DIRECTION

def create_application():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    # Conversation handler for /addalert
    addalert_conv = ConversationHandler(
        entry_points=[CommandHandler("addalert", addalert)],
        states={
            SELECTING_TICKER: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_ticker)],
            SETTING_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_target)],
            SELECTING_DIRECTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_direction)]
        },
        fallbacks=[],
    )
    app.add_handler(addalert_conv)
    app.add_handler(CommandHandler("addalert", addalert))
    app.add_handler(CommandHandler("myalert", myalerts))
    app.add_handler(CommandHandler("help", help_command))

    return app
   