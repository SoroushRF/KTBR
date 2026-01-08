"""
KTBR - Privacy Protection Telegram Bot
Main entry point - starts the bot.
"""

from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from config import BOT_TOKEN, ALLOWED_USERNAMES, logger
from handlers import (
    start_command,
    upload_command,
    stop_command,
    clear_command,
    mode_command,
    mode_callback,
    handle_video,
    voice_level_callback,
    handle_photo,
    handle_document,
    handle_unknown,
    get_report_handler,
    get_request_handler,
    admin_callback_handler,
)


async def post_init(application: Application):
    """Set up bot commands after initialization."""
    commands = [
        BotCommand("start", "Show welcome message and info"),
        BotCommand("mode", "Switch Face Blur / Voice modes"),
        BotCommand("upload", "How to upload files"),
        BotCommand("stop", "Cancel current processing"),
        BotCommand("report", "Report a bug"),
        BotCommand("clear", "How to delete your chat"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Bot commands registered with Telegram")


def main():
    """Start the bot."""
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("=" * 60)
        print("ERROR: Please set your bot token!")
        print("=" * 60)
        print("\n1. Go to @BotFather on Telegram")
        print("2. Create a new bot with /newbot")
        print("3. Set BOT_TOKEN in your .env file")
        print("=" * 60)
        return
    
    print("=" * 60)
    print("KTBR - Privacy Protection Telegram Bot")
    print("=" * 60)
    print(f"Allowed usernames: {ALLOWED_USERNAMES}")
    print("=" * 60)
    
    # Build application with concurrent updates enabled
    # This allows /stop to be processed while video processing is running
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        #.concurrent_updates(True)  # Disabled for stability
        .post_init(post_init)
        .build()
    )
    
    # Add command handlers
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("mode", mode_command))
    application.add_handler(CommandHandler("upload", upload_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("clear", clear_command))
    
    # Add callback handler for inline buttons (mode selection)
    application.add_handler(CallbackQueryHandler(mode_callback, pattern="^mode_"))
    
    # Add callback handler for voice level selection
    application.add_handler(CallbackQueryHandler(voice_level_callback, pattern="^voice_"))

    

    
    # Add conversation handlers (MUST be before standard message handlers)
    
    # Admin actions
    application.add_handler(CallbackQueryHandler(admin_callback_handler, pattern="^admin_"))

    # Report handler
    application.add_handler(get_report_handler())
    # Request access handler
    application.add_handler(get_request_handler())
    
    # Add message handlers
    application.add_handler(MessageHandler(filters.VIDEO, handle_video))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unknown))
    
    # Start polling
    print("Bot is running... Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

