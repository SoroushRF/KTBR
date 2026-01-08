from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from config import OWNER_ID, logger
from utils.auth import is_user_allowed, save_authorized_ids, load_authorized_ids
from utils.access_manager import (
    add_request,
    get_request_status,
    mark_ignored,
    remove_request,
    STATUS_PENDING,
    STATUS_IGNORED
)

# States
WAITING_REASON = 1

async def check_access_gatekeeper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Blocks unauthorized users and initiates the request flow.
    If authorized -> Continue (return ConversationHandler.END) - actually wait, this is tricky.
    
    Better approach: This handler catches EVERYTHING.
    If authorized -> Pass through (ignore, let other handlers handle it? No, handlers don't cascade easily in PTB unless using groups).
    
    Revised Strategy:
    This handler is registered with a high priority filter or as a fallback.
    Actually, let's make this a ConversationHandler that starts ONLY if user is NOT authorized.
    But how to detect? via a filter?
    
    Simpler: We make a standard MessageHandler that captures ALL TEXT/COMMANDS if filter='Not Authorized'.
    But filters in PTB are static.
    
    Standard pattern:
    Middleware logic isn't native. We'll use a wrapper or just check auth at start of this handler.
    If auth -> return conversation END (allow others to pick it up? No PTB stops at first match).
    
    Solution:
    The main bot.py will register this handler FIRST.
    Inside this handler, we check auth.
    If Auth -> `return None` (PTB legacy way to "pass" to next handler? No, `Application` doesn't support fallthrough easily).
    
    Correction:
    We need a custom Filter. `filters.create(check_auth)`.
    """
    pass # Placeholder comment for thought process

class UnauthorizedFilter(filters.BaseFilter):
    def filter(self, message):
        user = message.from_user
        if not user:
            return False
        # If user is owner, they are allowed
        if user.id == OWNER_ID:
            return False
        
        # Check standard auth
        is_allowed, _ = is_user_allowed(user.username, user.id)
        return not is_allowed

unauthorized_filter = UnauthorizedFilter()

async def request_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point for unauthorized users."""
    user = update.effective_user
    
    # Check if they already have a pending request
    status = get_request_status(user.id)
    
    if status in [STATUS_PENDING, STATUS_IGNORED]:
        await update.message.reply_text(
            "⏳ *Request Under Review*\n\n"
            "Your access request is still under review by the administrator.\n"
            "Please wait for a notification.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    # New Request
    await update.message.reply_text(
        "🚫 *Access Denied*\n\n"
        "You are not authorized to use this bot.\n"
        "To request access, please reply to this message with your **Name** or a brief note so the owner knows who you are.",
        parse_mode="Markdown"
    )
    return WAITING_REASON

async def receive_request_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User sent their note/name."""
    user = update.effective_user
    note = update.message.text
    
    # 1. Save Request
    add_request(user.id, user.first_name, user.username, note)
    
    # 2. Notify Admin
    if OWNER_ID != 0:
        keyboard = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"access_approve_{user.id}"),
                InlineKeyboardButton("❌ Silent Deny", callback_data=f"access_deny_{user.id}")
            ]
        ]
        
        user_display = f"{user.first_name}"
        if user.last_name:
            user_display += f" {user.last_name}"
        if user.username:
            user_display += f" (@{user.username})"
            
        try:
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=(
                    f"🔔 *New Access Request*\n\n"
                    f"👤 *User:* {user_display}\n"
                    f"🆔 *ID:* `{user.id}`\n\n"
                    f"📝 *Note:*\n_{note}_"
                ),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to notify owner: {e}")
    else:
        logger.warning("OWNER_ID not set. Request saved but admin not notified.")
    
    # 3. Confirm to User
    await update.message.reply_text(
        "✅ *Request Sent*\n\n"
        "Your request has been sent to the administrator.\n"
        "You will be notified if your access is approved.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cancel_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel conversation."""
    await update.message.reply_text("Action cancelled.")
    return ConversationHandler.END

async def access_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Admin Approve/Deny clicks."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    parts = data.split("_")
    action = parts[1] # approve or deny
    target_id = int(parts[2])
    
    # Check if request still exists or valid
    # Actually just proceed.
    
    if action == "approve":
        # 1. Add to authorized
        current_ids = load_authorized_ids()
        if target_id not in current_ids:
            current_ids.append(target_id)
            save_authorized_ids(current_ids)
            
        # 2. Clean up pending
        remove_request(target_id)
        
        # 3. Notify User
        try:
            await context.bot.send_message(
                target_id,
                "🎉 *Access Granted!*\n\n"
                "Your request has been approved. You can now use the bot.\n"
                "Send /start to begin.",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"Could not notify user {target_id}: {e}")
            
        # 4. Update Admin Message
        await query.edit_message_text(
            f"{query.message.text_markdown}\n\n"
            f"✅ *Approved*",
            parse_mode="Markdown"
        )
        
    elif action == "deny":
        # 1. Mark ignored
        mark_ignored(target_id)
        
        # 2. Update Admin Message (No user notification)
        await query.edit_message_text(
            f"{query.message.text_markdown}\n\n"
            f"❌ *Denied (Silently)*",
            parse_mode="Markdown"
        )

def get_access_handler():
    """Return the ConversationHandler for access requests."""
    # This handler triggers for ANY text/command ONLY if unauthorized
    return ConversationHandler(
        entry_points=[
            MessageHandler(unauthorized_filter & ~filters.UpdateType.EDITED, request_start)
        ],
        states={
            WAITING_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_request_note)],
        },
        fallbacks=[CommandHandler("cancel", cancel_request)],
        # We need per_user=True (default)
    )
