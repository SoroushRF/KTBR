"""
KTBR - Face Blurring Telegram Bot
Main entry point - starts the bot.
"""

from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

from config import BOT_TOKEN, ALLOWED_USERNAMES, logger
from handlers import (
    start_command,
    upload_command,
    stop_command,
    handle_video,
    handle_photo,
    handle_document,
    handle_unknown,
)


async def post_init(application: Application):
    """Set up bot commands after initialization."""
    commands = [
        BotCommand("start", "Show welcome message and info"),
        BotCommand("upload", "How to upload files"),
        BotCommand("stop", "Cancel current processing"),
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
    print("KTBR - Face Blur Telegram Bot")
    print("=" * 60)
    print(f"Allowed usernames: {ALLOWED_USERNAMES}")
    print("=" * 60)
    
    # Build application with concurrent updates enabled
    # This allows /stop to be processed while video processing is running
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)  # CRITICAL: Allows handlers to run in parallel
        .post_init(post_init)
        .build()
    )
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("upload", upload_command))
    application.add_handler(CommandHandler("stop", stop_command))
    
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
