from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.auth import is_user_allowed
from utils.access_manager import get_request_status, STATUS_PENDING, STATUS_IGNORED

def require_auth(func):
    """
    Decorator to check if user is authorized.
    If not, checks request status:
    - If Pending/Ignored: Shows 'Under Review' (Ghosting).
    - If New: Shows 'Access Denied' with 'Request Access' button.
    Stops execution of the wrapped function if unauthorized.
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user:
            return await func(update, context, *args, **kwargs)

        # 1. Check if Authorized
        is_allowed, msg = is_user_allowed(user.username, user.id)
        if is_allowed:
            return await func(update, context, *args, **kwargs)

        # 2. Check Pending/Ignored Status
        status = get_request_status(user.id)
        
        # Use effective_message to handle both Messages and CallbackQueries safely
        message = update.effective_message
        if not message:
            return # Should not happen in standard handlers

        if status in [STATUS_PENDING, STATUS_IGNORED]:
             text = (
                "⏳ **Request Under Review**\n\n"
                "Your access request is currently being reviewed.\n"
                "Please wait for the administrator."
            )
             # Reply quoting the user's message if possible
             await message.reply_text(text, parse_mode="Markdown")
             return

        # 3. Unauthorized & New -> Show Button
        keyboard = [
            [InlineKeyboardButton("📝 Request Access", callback_data="request_access_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await message.reply_text(
            "🚫 **Access Denied**\n\n"
            "You are not authorized to use this bot.\n"
            "To request access, click the button below.",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return

    return wrapper
