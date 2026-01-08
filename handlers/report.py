import os
import uuid
from datetime import datetime
from telegram import Update
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
)
from config import logger

# States
REPORT_CAPTION, REPORT_IMAGES = range(2)

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the report conversation."""
    logger.info(f"User {update.effective_user.username} started a report.")
    
    await update.message.reply_text(
        "📝 *New Bug Report*\n\n"
        "Please briefly describe the bug or issue you encountered.\n"
        "This explanation will be saved as the caption for your report.\n\n"
        "Send /cancel to abort at any time.",
        parse_mode="Markdown"
    )
    return REPORT_CAPTION

async def report_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store the caption and ask for images."""
    caption = update.message.text
    context.user_data['report_caption'] = caption
    context.user_data['report_images'] = []
    
    await update.message.reply_text(
        "✅ Caption saved.\n\n"
        "Now, you can upload up to **5 screenshots/images** related to the issue.\n\n"
        "• Send images one by one or as an album.\n"
        "• If you don't have images, just send /done.\n"
        "• When finished uploading, send /done.",
        parse_mode="Markdown"
    )
    return REPORT_IMAGES

async def report_images(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle image uploads."""
    current_images = context.user_data.get('report_images', [])
    
    # If user sends text instead of /done or images (and it's not a command because filters handled it? No wait context filter handles text/video)
    # The handler config uses filters.PHOTO. 
    # If we want to catch user mistakes (sending text in image state), we might need a fallback or broad filter.
    # But let's stick to the happy path + command fallback.
    
    if len(current_images) >= 5:
        await update.message.reply_text(
            "⚠️ **Limit Reached**\n\n"
            "You have already uploaded 5 images. We will only keep these 5.\n"
            "Please send /done to submit your report.",
            parse_mode="Markdown"
        )
        return REPORT_IMAGES

    # Get the file_id of the largest photo
    photo = update.message.photo[-1]
    file_id = photo.file_id
    
    # Avoid duplicates if user sends same image? Tricky to distinct without hash. 
    # Just append.
    current_images.append(file_id)
    context.user_data['report_images'] = current_images
    
    count = len(current_images)
    
    msg = f"📸 Image {count}/5 received."
    if count >= 5:
        msg += "\n\nLimit reached. Please send /done to submit."
    
    await update.message.reply_text(msg)
    return REPORT_IMAGES

async def report_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save the report."""
    user = update.effective_user
    username = user.username or "unknown_user"
    user_id = user.id
    
    # Generate unique report ID
    report_uuid = uuid.uuid4().hex[:8]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder_name = f"{timestamp}_{report_uuid}_{username}"
    
    # Base directory
    base_dir = "reports"
    report_dir = os.path.join(base_dir, folder_name)
    os.makedirs(report_dir, exist_ok=True)
    
    caption = context.user_data.get('report_caption', "No caption provided")
    image_file_ids = context.user_data.get('report_images', [])
    
    # Save Report Info
    info_path = os.path.join(report_dir, "report_info.txt")
    with open(info_path, "w", encoding="utf-8") as f:
        f.write(f"Report ID: {report_uuid}\n")
        f.write(f"Timestamp: {timestamp}\n")
        f.write(f"User: {username} (ID: {user_id})\n")
        f.write("-" * 30 + "\n")
        f.write("CAPTION:\n")
        f.write(caption + "\n")
        f.write("-" * 30 + "\n")
        f.write(f"Images count: {len(image_file_ids)}\n")
    
    await update.message.reply_text("💾 Saving your report (this might take a moment if you sent images)...")
    
    # Download images
    saved_count = 0
    for i, file_id in enumerate(image_file_ids):
        try:
            file = await context.bot.get_file(file_id)
            # Determine extension (default to jpg if unknown, but usually we can infer or it doesn't matter much for display)
            # file.file_path might have extension
            ext = ".jpg"
            if file.file_path:
                _, ext_web = os.path.splitext(file.file_path)
                if ext_web:
                    ext = ext_web
            
            save_path = os.path.join(report_dir, f"evidence_{i+1}{ext}")
            await file.download_to_drive(save_path)
            saved_count += 1
        except Exception as e:
            logger.error(f"Failed to download image {i} for report {report_uuid}: {e}")
            
    logger.info(f"Report {report_uuid} saved by {username} with {saved_count} images.")
    
    await update.message.reply_text(
        "✅ **Report Submitted Successfully!**\n\n"
        f"Reference ID: `{report_uuid}`\n"
        "Thank you for helping us improve.",
        parse_mode="Markdown"
    )
    
    context.user_data.clear()
    return ConversationHandler.END

async def report_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the conversation."""
    await update.message.reply_text("❌ Report cancelled.")
    context.user_data.clear()
    return ConversationHandler.END

def get_report_handler():
    """Return the ConversationHandler for the report flow."""
    return ConversationHandler(
        entry_points=[CommandHandler("report", report_command)],
        states={
            REPORT_CAPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, report_caption)],
            REPORT_IMAGES: [
                MessageHandler(filters.PHOTO, report_images),
                CommandHandler("done", report_done)
            ],
        },
        fallbacks=[CommandHandler("cancel", report_cancel)],
        # Allow /done to work in caption state? No, user must provide caption first based on flow.
    )
