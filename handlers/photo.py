"""
KTBR - Photo Handler
Handles photo uploads and processing.
"""

import os
import asyncio
import tempfile
from io import BytesIO

from telegram import Update
from telegram.ext import ContextTypes

from config import (
    MAX_IMAGE_SIZE_MB,
    MAX_IMAGE_DIMENSION,
    ESTIMATE_IMAGE_SEC_PER_MB,
    logger
)
from utils.auth import is_user_allowed
from processors.face_blur import blur_faces_in_image


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo uploads."""
    user = update.effective_user
    username = user.username
    user_id = user.id
    
    is_allowed, message = is_user_allowed(username, user_id)
    if not is_allowed:
        await update.message.reply_text(message)
        return
    
    # Get the largest photo
    photo = update.message.photo[-1] if update.message.photo else None
    
    if not photo:
        await update.message.reply_text("❌ No photo detected. Please send a valid image.")
        return
    
    # Check dimensions
    if photo.width > MAX_IMAGE_DIMENSION or photo.height > MAX_IMAGE_DIMENSION:
        await update.message.reply_text(
            f"❌ Image resolution too high!\n\n"
            f"Your image: {photo.width}x{photo.height}\n"
            f"Maximum: {MAX_IMAGE_DIMENSION}x{MAX_IMAGE_DIMENSION}"
        )
        return
    
    # Check file size
    file_size_mb = photo.file_size / (1024 * 1024)
    
    if file_size_mb > MAX_IMAGE_SIZE_MB:
        await update.message.reply_text(
            f"❌ Image too large!\n\n"
            f"Your file: {file_size_mb:.1f} MB\n"
            f"Maximum: {MAX_IMAGE_SIZE_MB} MB"
        )
        return
    
    # Estimate processing time
    estimated_time = max(int(file_size_mb * ESTIMATE_IMAGE_SEC_PER_MB), 2)
    
    await update.message.reply_text(
        f"⏳ **Processing your image...**\n\n"
        f"📐 Resolution: {photo.width}x{photo.height}\n"
        f"⏱️ Estimated time: ~{estimated_time} seconds\n\n"
        f"Please wait...",
        parse_mode='Markdown'
    )
    
    # Download and process
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = os.path.join(temp_dir, "input.jpg")
            output_path = os.path.join(temp_dir, "output.jpg")
            
            # Download file
            file = await context.bot.get_file(photo.file_id)
            await file.download_to_drive(input_path)
            
            # Process image in background thread
            success = await asyncio.to_thread(blur_faces_in_image, input_path, output_path)
            
            if success and os.path.exists(output_path):
                with open(output_path, 'rb') as f:
                    image_data = f.read()
                
                await update.message.reply_document(
                    document=BytesIO(image_data),
                    filename="blurred_image.jpg",
                    caption="✅ **Done!** Here's your processed image with blurred faces."
                )
                await update.message.reply_text(
                    "📤 Send another **video** or **image** to blur faces.",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text("❌ Failed to process image. Please try again.\n\n📤 Send another file to try again.")
    
    except Exception as e:
        logger.error(f"Error processing photo: {e}")
        await update.message.reply_text(f"❌ An error occurred: {str(e)}")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle document uploads (for images/videos sent as files)."""
    from handlers.video import handle_video  # Import here to avoid circular import
    
    document = update.message.document
    
    if not document or not document.mime_type:
        await update.message.reply_text("❌ Unsupported file type.")
        return
    
    mime_type = document.mime_type.lower()
    
    if mime_type.startswith('video/'):
        await handle_video(update, context)
    elif mime_type.startswith('image/'):
        # For images sent as documents
        user = update.effective_user
        is_allowed, message = is_user_allowed(user.username, user.id)
        if not is_allowed:
            await update.message.reply_text(message)
            return
        
        file_size_mb = document.file_size / (1024 * 1024)
        
        if file_size_mb > MAX_IMAGE_SIZE_MB:
            await update.message.reply_text(
                f"❌ Image too large!\n\n"
                f"Your file: {file_size_mb:.1f} MB\n"
                f"Maximum: {MAX_IMAGE_SIZE_MB} MB"
            )
            return
        
        estimated_time = max(int(file_size_mb * ESTIMATE_IMAGE_SEC_PER_MB), 2)
        
        await update.message.reply_text(
            f"⏳ **Processing your image...**\n\n"
            f"📊 File size: {file_size_mb:.1f} MB\n"
            f"⏱️ Estimated time: ~{estimated_time} seconds\n\n"
            f"Please wait...",
            parse_mode='Markdown'
        )
        
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                ext = os.path.splitext(document.file_name)[1] if document.file_name else ".jpg"
                input_path = os.path.join(temp_dir, f"input{ext}")
                output_path = os.path.join(temp_dir, f"output{ext}")
                
                file = await context.bot.get_file(document.file_id)
                await file.download_to_drive(input_path)
                
                success = await asyncio.to_thread(blur_faces_in_image, input_path, output_path)
                
                if success and os.path.exists(output_path):
                    await update.message.reply_document(
                        document=open(output_path, 'rb'),
                        filename=f"blurred_{document.file_name or 'image.jpg'}",
                        caption="✅ **Done!** Here's your processed image with blurred faces."
                    )
                else:
                    await update.message.reply_text("❌ Failed to process image. Please try again.")
        except Exception as e:
            logger.error(f"Error processing document: {e}")
            await update.message.reply_text(f"❌ An error occurred: {str(e)}")
    else:
        await update.message.reply_text(
            "❌ Unsupported file type.\n\n"
            "Please send a video (.mp4, .avi, .mov) or image (.jpg, .png)."
        )


async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle unknown messages."""
    user = update.effective_user
    is_allowed, message = is_user_allowed(user.username, user.id)
    
    if not is_allowed:
        await update.message.reply_text(message)
        return
    
    await update.message.reply_text(
        "📤 Please send me a **video** or **image** to blur faces.\n\n"
        "Use /start to see the file limits.",
        parse_mode='Markdown'
    )
