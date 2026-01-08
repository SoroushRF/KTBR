"""
KTBR - Command Handlers
/start, /upload, /stop, /clear, /mode commands
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import (
    MAX_VIDEO_DURATION_SECONDS, 
    MAX_VIDEO_SIZE_MB, 
    MAX_IMAGE_SIZE_MB, 
    MAX_IMAGE_DIMENSION,
    AUTO_DELETE_SECONDS,
    active_tasks,
    user_modes,
    logger
)
from utils.auth import is_user_allowed


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user = update.effective_user
    username = user.username
    user_id = user.id
    
    is_allowed, message = is_user_allowed(username, user_id)
    
    if not is_allowed:
        await update.message.reply_text(message)
        return
    
    # Get current mode
    current_mode = get_user_mode(user_id)
    mode_emoji = "🎭" if current_mode == "face" else "🔊"
    mode_name = "Face Blur" if current_mode == "face" else "Voice Anonymize"
    
    welcome_message = f"""
👋 Welcome, @{username}!

🔒 **KTBR - Privacy Protection Bot**

{mode_emoji} **Current Mode: {mode_name}**
Use /mode to switch modes.

📤 **Just send me a file:**

📹 **Video:**
• Max duration: {MAX_VIDEO_DURATION_SECONDS} seconds
• Max size: {MAX_VIDEO_SIZE_MB} MB

🖼️ **Image:** (Face Blur mode only)
• Max resolution: Full HD ({MAX_IMAGE_DIMENSION}px)  
• Max size: {MAX_IMAGE_SIZE_MB} MB

🗑️ **Privacy:**
• Results auto-delete in {AUTO_DELETE_SECONDS} seconds
• Save files immediately after receiving!

📋 **Commands:**
/start - Show this welcome message
/mode - Switch Face Blur / Voice modes
/upload - How to upload files
/stop - Cancel current processing
/clear - How to delete your chat

Simply upload a file and I'll process it for you!
"""
    await update.message.reply_text(welcome_message, parse_mode='Markdown')


async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /upload command - explains how to upload."""
    user = update.effective_user
    is_allowed, message = is_user_allowed(user.username, user.id)
    
    if not is_allowed:
        await update.message.reply_text(message)
        return
    
    upload_message = f"""
📤 **How to Upload Files**

**Option 1: Direct Send**
Just drag & drop or attach a video/image directly in this chat!

**Option 2: Forward**
Forward a video or image from another chat.

**Option 3: File Upload**
Click 📎 and select your file.

━━━━━━━━━━━━━━━━━━━━━

📹 **Video Limits:**
• Max duration: {MAX_VIDEO_DURATION_SECONDS} seconds
• Max size: {MAX_VIDEO_SIZE_MB} MB
• Formats: MP4, AVI, MOV, etc.

🖼️ **Image Limits:**
• Max resolution: {MAX_IMAGE_DIMENSION}x{MAX_IMAGE_DIMENSION}
• Max size: {MAX_IMAGE_SIZE_MB} MB
• Formats: JPG, PNG, etc.

━━━━━━━━━━━━━━━━━━━━━

⏳ Processing time depends on file size.
Use /stop to cancel if needed.
"""
    await update.message.reply_text(upload_message, parse_mode='Markdown')


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stop command - cancels current processing or leaves the queue."""
    user = update.effective_user
    user_id = user.id
    
    is_allowed, message = is_user_allowed(user.username, user.id)
    if not is_allowed:
        await update.message.reply_text(message)
        return
    
    # Imports for queue management
    from utils.queue_manager import is_in_queue, remove_from_queue, notify_next_in_queue
    from config import active_tasks
    
    # 1. Check if they are in the queue
    if is_in_queue(user_id):
        remove_from_queue(user_id)
        await update.message.reply_text(
            "🛑 **Left the queue.**\n\nYour file will not be processed.",
            parse_mode='Markdown'
        )
        # Notify whoever is next to update their positions
        asyncio.create_task(notify_next_in_queue(context))
        return

    # 2. Check if they have an active task
    if user_id not in active_tasks:
        await update.message.reply_text(
            "ℹ️ No active processing or queue position to stop.\n\n"
            "Send a video or image to start processing."
        )
        return
    
    cancel_event = active_tasks[user_id].get("cancel_event")
    if cancel_event:
        cancel_event.set()
        logger.info(f"User {user_id} - cancel event SET")
    
    await update.message.reply_text(
        "🛑 **Stopping processing...**\n\n"
        "The current operation is being aborted.\n"
        "Please wait for confirmation.",
        parse_mode='Markdown'
    )
    logger.info(f"User {user_id} requested cancellation")


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /clear command - explains how to delete chat."""
    user = update.effective_user
    is_allowed, message = is_user_allowed(user.username, user.id)
    
    if not is_allowed:
        await update.message.reply_text(message)
        return
    
    clear_message = """
🗑️ **How to Clear Your Chat**

**Bot messages** are auto-deleted after processing.

**Your messages** must be deleted manually:

━━━━━━━━━━━━━━━━━━━━━

📱 **On Mobile (iOS/Android):**
1. Long-press on your message
2. Tap "Delete"
3. Select "Delete for me and bot" (if available)
4. Or select "Delete for me"

💻 **On Desktop:**
1. Right-click on your message
2. Click "Delete"
3. Check "Also delete for the bot" (if available)
4. Click "Delete"

━━━━━━━━━━━━━━━━━━━━━

🔒 **For maximum privacy:**
• Delete the entire chat:
  - Click chat name at top
  - Scroll down → "Delete Chat"

⚠️ **Important:** 
The bot cannot delete YOUR messages due to Telegram's privacy policy.
Only YOU can delete what you sent.
"""
    await update.message.reply_text(clear_message, parse_mode='Markdown')


def get_user_mode(user_id: int) -> str:
    """Get user's current mode, default is 'face'."""
    if user_id not in user_modes:
        user_modes[user_id] = {"mode": "face", "voice_level": "fast"}
    return user_modes[user_id]["mode"]


async def mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /mode command - switch between Face Blur and Voice Anonymize."""
    user = update.effective_user
    is_allowed, message = is_user_allowed(user.username, user.id)
    
    if not is_allowed:
        await update.message.reply_text(message)
        return
    
    current_mode = get_user_mode(user.id)
    current_emoji = "🎭" if current_mode == "face" else "🔊"
    current_name = "Face Blur" if current_mode == "face" else "Voice Anonymize"
    
    keyboard = [
        [
            InlineKeyboardButton("🎭 Face Blur", callback_data="mode_face"),
            InlineKeyboardButton("🔊 Voice Anonymize", callback_data="mode_voice"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"🔧 **Select Processing Mode**\n\n"
        f"Current mode: {current_emoji} **{current_name}**\n\n"
        f"🎭 **Face Blur** - Blur faces in videos/images\n"
        f"🔊 **Voice Anonymize** - Alter voice in videos (no images)\n\n"
        f"Tap a button below to switch:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


async def mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback when user clicks mode selection buttons."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    callback_data = query.data
    
    # Initialize user mode if not exists
    if user_id not in user_modes:
        user_modes[user_id] = {"mode": "face", "voice_level": "fast"}
    
    if callback_data == "mode_face":
        user_modes[user_id]["mode"] = "face"
        await query.edit_message_text(
            "✅ **Mode switched to: 🎭 Face Blur**\n\n"
            "Send a video or image to blur faces.\n\n"
            "Use /mode to switch modes anytime.",
            parse_mode='Markdown'
        )
        logger.info(f"User {user_id} switched to Face Blur mode")
        
    elif callback_data == "mode_voice":
        user_modes[user_id]["mode"] = "voice"
        await query.edit_message_text(
            "✅ **Mode switched to: 🔊 Voice Anonymize**\n\n"
            "Send a **video** to anonymize the voice.\n"
            "⚠️ Images are not supported in this mode.\n\n"
            "Use /mode to switch modes anytime.",
            parse_mode='Markdown'
        )
        logger.info(f"User {user_id} switched to Voice Anonymize mode")
