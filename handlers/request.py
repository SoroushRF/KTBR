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

# Conversation States
WAITING_NOTE = 1

async def start_request_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Triggered when user clicks 'Request Access'.
    """
    query = update.callback_query
    await query.answer()
    
    # Double check if already pending (just in case)
    user_id = query.from_user.id
    status = get_request_status(user_id)
    if status in [STATUS_PENDING, STATUS_IGNORED]:
        await query.edit_message_text(
            "⏳ **Request Under Review**\n\n"
            "You already have a pending request.\n"
            "Please wait for the administrator.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    await query.edit_message_text(
        "📝 **Request Access**\n\n"
        "Please reply to this message with a **brief note** introducing yourself.\n"
        "The owner will review your request.",
        parse_mode="Markdown"
    )
    return WAITING_NOTE

async def receive_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User sent the note."""
    user = update.effective_user
    note = update.message.text
    
    # Save Request
    add_request(user.id, user.first_name, user.username, note)
    
    # Notify Admin
    if OWNER_ID != 0:
        keyboard = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"admin_approve_{user.id}"),
                InlineKeyboardButton("❌ Deny", callback_data=f"admin_deny_{user.id}")
            ]
        ]
        
        user_display = f"{user.first_name}"
        if user.last_name: user_display += f" {user.last_name}"
        if user.username: user_display += f" (@{user.username})"
            
        try:
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=(
                    f"🔔 **New Access Request**\n\n"
                    f"👤 **User:** {user_display}\n"
                    f"🆔 **ID:** `{user.id}`\n\n"
                    f"📝 **Note:**\n_{note}_"
                ),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to notify owner: {e}")
    
    await update.message.reply_text(
        "✅ **Request Sent**\n\n"
        "Your request has been forwarded to the administrator.\n"
        "You will be notified here if approved.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cancel_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel flow."""
    await update.message.reply_text("❌ Request cancelled.")
    return ConversationHandler.END

def get_request_handler():
    """Return the ConversationHandler."""
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(start_request_flow, pattern="^request_access_start$")],
        states={
            WAITING_NOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_note)]
        },
        fallbacks=[CommandHandler("cancel", cancel_request)],
    )

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Admin Approve/Deny clicks."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    # Format: admin_approve_123456 or admin_deny_123456
    parts = data.split("_")
    action = parts[1] # approve or deny
    target_id = int(parts[2])
    
    if action == "approve":
        # 1. Authorize
        from utils.auth import add_authorized_user
        add_authorized_user(target_id)
        
        # 2. Clean up request
        remove_request(target_id)
        
        # 3. Notify User
        try:
            await context.bot.send_message(
                target_id,
                "🎉 **Access Granted!**\n\n"
                "Your request has been approved.\n"
                "Send /start to begin.",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"Could not notify user {target_id}: {e}")
            
        # 4. Update Admin Message
        await query.edit_message_text(
            f"{query.message.text_markdown}\n\n"
            f"✅ **Approved**",
            parse_mode="Markdown"
        )
        
    elif action == "deny":
        # 1. Mark ignored
        mark_ignored(target_id)
        
        # 2. Update Admin Message
        await query.edit_message_text(
            f"{query.message.text_markdown}\n\n"
            f"❌ **Denied** (Silently)",
            parse_mode="Markdown"
        )
