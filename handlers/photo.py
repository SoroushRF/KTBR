"""
KTBR - Photo Handler
Handles photo uploads and processing with auto-delete.
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
    AUTO_DELETE_SECONDS,
    user_modes,
    logger
)
from utils.auth import is_user_allowed
from processors.face_blur import blur_faces_in_image


def get_user_mode(user_id: int) -> str:
    """Get user's current mode, default is 'face'."""
    if user_id not in user_modes:
        user_modes[user_id] = {"mode": "face", "voice_level": "fast"}
    return user_modes[user_id]["mode"]


async def delete_messages_after_delay(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_ids: list, delay: int):
    """Delete messages after a delay."""
    try:
        await asyncio.sleep(delay)
        
        for msg_id in message_ids:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception as e:
                logger.warning(f"Could not delete message {msg_id}: {e}")
        
        reminder = await context.bot.send_message(
            chat_id=chat_id,
            text="🗑️ **Bot messages deleted.**\n\n"
                 "⚠️ **Please delete your original file manually:**\n"
                 "Long-press your message → Delete\n\n"
                 "Use /clear for instructions.",
            parse_mode='Markdown'
        )
        
        await asyncio.sleep(30)
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=reminder.message_id)
        except:
            pass
            
    except Exception as e:
        logger.error(f"Error in delete_messages_after_delay: {e}")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo uploads."""
    user = update.effective_user
    username = user.username
    user_id = user.id
    chat_id = update.effective_chat.id
    
    messages_to_delete = []
    
    is_allowed, message = is_user_allowed(username, user_id)
    if not is_allowed:
        await update.message.reply_text(message)
        return
    
    # Check if user is in voice mode - reject images
    current_mode = get_user_mode(user_id)
    if current_mode == "voice":
        await update.message.reply_text(
            "❌ **Voice mode only works with videos!**\n\n"
            "📹 Send a **video** to anonymize voice.\n"
            "🎭 Or use /mode to switch to Face Blur for images.",
            parse_mode='Markdown'
        )
        return
    
    photo = update.message.photo[-1] if update.message.photo else None
    
    if not photo:
        await update.message.reply_text("❌ No photo detected. Please send a valid image.")
        return
    
    if photo.width > MAX_IMAGE_DIMENSION or photo.height > MAX_IMAGE_DIMENSION:
        await update.message.reply_text(
            f"❌ Image resolution too high!\n\n"
            f"Your image: {photo.width}x{photo.height}\n"
            f"Maximum: {MAX_IMAGE_DIMENSION}x{MAX_IMAGE_DIMENSION}"
        )
        return
    
    file_size_mb = photo.file_size / (1024 * 1024)
    
    if file_size_mb > MAX_IMAGE_SIZE_MB:
        await update.message.reply_text(
            f"❌ Image too large!\n\n"
            f"Your file: {file_size_mb:.1f} MB\n"
            f"Maximum: {MAX_IMAGE_SIZE_MB} MB"
        )
        return
    
    estimated_time = max(int(file_size_mb * ESTIMATE_IMAGE_SEC_PER_MB), 2)
    
    processing_msg = await update.message.reply_text(
        f"⏳ **Processing your image...**\n\n"
        f"📐 Resolution: {photo.width}x{photo.height}\n"
        f"⏱️ Estimated time: ~{estimated_time} seconds\n\n"
        f"Please wait...",
        parse_mode='Markdown'
    )
    messages_to_delete.append(processing_msg.message_id)
    
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = os.path.join(temp_dir, "input.jpg")
            output_path = os.path.join(temp_dir, "output.jpg")
            
            file = await context.bot.get_file(photo.file_id)
            await file.download_to_drive(input_path)
            
            success = await asyncio.to_thread(blur_faces_in_image, input_path, output_path)
            
            if success and os.path.exists(output_path):
                with open(output_path, 'rb') as f:
                    image_data = f.read()
                
                result_msg = await update.message.reply_document(
                    document=BytesIO(image_data),
                    filename="blurred_image.jpg",
                    caption=f"✅ **Done!** Blurred image ready.\n\n"
                            f"⚠️ **SAVE NOW!** Auto-deleting in {AUTO_DELETE_SECONDS} seconds..."
                )
                messages_to_delete.append(result_msg.message_id)
                
                warning_msg = await update.message.reply_text(
                    f"�️ **Auto-delete in {AUTO_DELETE_SECONDS} seconds!**\n\n"
                    f"📥 Save the image above NOW!\n"
                    f"🔒 All bot messages will be deleted.\n\n"
                    f"⚠️ Please also delete your original file manually.",
                    parse_mode='Markdown'
                )
                messages_to_delete.append(warning_msg.message_id)
                
                asyncio.create_task(
                    delete_messages_after_delay(context, chat_id, messages_to_delete, AUTO_DELETE_SECONDS)
                )
            else:
                error_msg = await update.message.reply_text(
                    "❌ Failed to process image. Please try again.\n\n📤 Send another file to try again."
                )
                messages_to_delete.append(error_msg.message_id)
    
    except Exception as e:
        logger.error(f"Error processing photo: {e}")
        error_msg = await update.message.reply_text(f"❌ An error occurred: {str(e)}")
        messages_to_delete.append(error_msg.message_id)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle document uploads (for images/videos sent as files)."""
    from handlers.video import handle_video
    
    document = update.message.document
    chat_id = update.effective_chat.id
    
    if not document or not document.mime_type:
        await update.message.reply_text("❌ Unsupported file type.")
        return
    
    mime_type = document.mime_type.lower()
    
    if mime_type.startswith('video/'):
        await handle_video(update, context)
    elif mime_type.startswith('image/'):
        user = update.effective_user
        is_allowed, message = is_user_allowed(user.username, user.id)
        if not is_allowed:
            await update.message.reply_text(message)
            return
        
        messages_to_delete = []
        file_size_mb = document.file_size / (1024 * 1024)
        
        if file_size_mb > MAX_IMAGE_SIZE_MB:
            await update.message.reply_text(
                f"❌ Image too large!\n\n"
                f"Your file: {file_size_mb:.1f} MB\n"
                f"Maximum: {MAX_IMAGE_SIZE_MB} MB"
            )
            return
        
        estimated_time = max(int(file_size_mb * ESTIMATE_IMAGE_SEC_PER_MB), 2)
        
        processing_msg = await update.message.reply_text(
            f"⏳ **Processing your image...**\n\n"
            f"📊 File size: {file_size_mb:.1f} MB\n"
            f"⏱️ Estimated time: ~{estimated_time} seconds\n\n"
            f"Please wait...",
            parse_mode='Markdown'
        )
        messages_to_delete.append(processing_msg.message_id)
        
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                ext = os.path.splitext(document.file_name)[1] if document.file_name else ".jpg"
                input_path = os.path.join(temp_dir, f"input{ext}")
                output_path = os.path.join(temp_dir, f"output{ext}")
                
                file = await context.bot.get_file(document.file_id)
                await file.download_to_drive(input_path)
                
                success = await asyncio.to_thread(blur_faces_in_image, input_path, output_path)
                
                if success and os.path.exists(output_path):
                    with open(output_path, 'rb') as f:
                        image_data = f.read()
                    
                    result_msg = await update.message.reply_document(
                        document=BytesIO(image_data),
                        filename=f"blurred_{document.file_name or 'image.jpg'}",
                        caption=f"✅ **Done!** Blurred image ready.\n\n"
                                f"⚠️ **SAVE NOW!** Auto-deleting in {AUTO_DELETE_SECONDS} seconds..."
                    )
                    messages_to_delete.append(result_msg.message_id)
                    
                    warning_msg = await update.message.reply_text(
                        f"🗑️ **Auto-delete in {AUTO_DELETE_SECONDS} seconds!**\n\n"
                        f"📥 Save the image above NOW!\n"
                        f"🔒 All bot messages will be deleted.\n\n"
                        f"⚠️ Please also delete your original file manually.",
                        parse_mode='Markdown'
                    )
                    messages_to_delete.append(warning_msg.message_id)
                    
                    asyncio.create_task(
                        delete_messages_after_delay(context, chat_id, messages_to_delete, AUTO_DELETE_SECONDS)
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
