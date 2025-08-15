from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler, CallbackQueryHandler, PreCheckoutQueryHandler
from core.handlers import start, addalert, select_ticker, select_target, select_direction, myalerts, delete_alert_callback, upgrade, help_command
from config import BOT_TOKEN
from core.state import SELECTING_TICKER, SETTING_TARGET, SELECTING_DIRECTION
from core.subscription import precheckout_callback, successful_payment_callback

# --- Create the Telegram Application (bot) with the necessary handlers ---
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
    app.add_handler(CommandHandler("myalerts", myalerts))
    app.add_handler(CallbackQueryHandler(delete_alert_callback, pattern=r"^delete_\d+$"))
    app.add_handler(CommandHandler("upgrade", upgrade))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(CommandHandler("help", help_command))

    return app
   