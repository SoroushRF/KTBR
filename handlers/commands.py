"""
KTBR - Command Handlers
/start, /upload, /stop, /clear commands
"""

from telegram import Update
from telegram.ext import ContextTypes

from config import (
    MAX_VIDEO_DURATION_SECONDS, 
    MAX_VIDEO_SIZE_MB, 
    MAX_IMAGE_SIZE_MB, 
    MAX_IMAGE_DIMENSION,
    AUTO_DELETE_SECONDS,
    active_tasks,
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
    
    welcome_message = f"""
👋 Welcome, @{username}!

🔒 **KTBR - Face Blur Bot**

I can blur faces in your videos and images.

📤 **Just send me a file:**

📹 **Video:**
• Max duration: {MAX_VIDEO_DURATION_SECONDS} seconds
• Max size: {MAX_VIDEO_SIZE_MB} MB

🖼️ **Image:**
• Max resolution: Full HD ({MAX_IMAGE_DIMENSION}px)  
• Max size: {MAX_IMAGE_SIZE_MB} MB

🗑️ **Privacy:**
• Results auto-delete in {AUTO_DELETE_SECONDS} seconds
• Save files immediately after receiving!

📋 **Commands:**
/start - Show this welcome message
/upload - How to upload files
/stop - Cancel current processing
/clear - How to delete your chat

Simply upload a video or image and I'll process it for you!
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
    """Handle /stop command - cancels current processing."""
    user = update.effective_user
    user_id = user.id
    
    is_allowed, message = is_user_allowed(user.username, user.id)
    if not is_allowed:
        await update.message.reply_text(message)
        return
    
    if user_id not in active_tasks:
        await update.message.reply_text(
            "ℹ️ No active processing to stop.\n\n"
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
