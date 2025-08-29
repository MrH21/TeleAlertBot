from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler, CallbackQueryHandler, PTBUserWarning
from core.handlers import start, addalert, select_ticker, select_target, select_direction, myalerts, delete_alert_callback, whales, whale_button_handler, upgrade, help_command, stats, broadcast
from config import BOT_TOKEN
from core.state import SELECTING_TICKER, SETTING_TARGET, SELECTING_DIRECTION
import warnings

# Suppress that specific PTB warning
warnings.filterwarnings(
    action="ignore",
    message=r".*CallbackQueryHandler",
    category=PTBUserWarning
)

# --- Create the Telegram Application (bot) with the necessary handlers ---
def create_application():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    # Conversation handler for /addalert
    addalert_conv = ConversationHandler(
        entry_points=[CommandHandler("addalert", addalert)],
        states={
            SELECTING_TICKER: [CallbackQueryHandler(select_ticker)],
            SETTING_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_target)],
            SELECTING_DIRECTION: [CallbackQueryHandler(select_direction)]
        },
        per_message=False,
        fallbacks=[],
    )
    app.add_handler(addalert_conv)
    app.add_handler(CommandHandler("myalerts", myalerts))
    app.add_handler(CallbackQueryHandler(delete_alert_callback, pattern=r"^delete_\d+$"))
    app.add_handler(CommandHandler("whales", whales))
    app.add_handler(CallbackQueryHandler(whale_button_handler))
    app.add_handler(CommandHandler("upgrade", upgrade))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("help", help_command))

    return app
   