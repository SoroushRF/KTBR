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
    active_tasks,
    logger
)
from utils.auth import is_user_allowed
from utils.queue_manager import (
    is_server_busy,
    is_on_cooldown,
    get_cooldown_remaining,
    set_cooldown,
    add_to_queue,
    remove_from_queue,
    estimate_wait_time,
    format_wait_time,
    notify_next_in_queue,
)
from processors.face_blur import blur_faces_in_image
from utils.decorators import require_auth


def get_user_mode(user_id: int) -> dict:
    """Get user's current mode settings."""
    if user_id not in user_modes:
        user_modes[user_id] = {"mode": "face", "voice_level": "fast"}
    return user_modes[user_id]


async def delete_messages_after_delay(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_ids: list, delay: int):
    """Delete messages after a delay."""
    try:
        await asyncio.sleep(delay)
        for msg_id in message_ids:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception as e:
                logger.warning(f"Could not delete message {msg_id}: {e}")
    except Exception as e:
        logger.error(f"Error in delete_messages_after_delay: {e}")


@require_auth
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE, queued_data: dict = None):
    """Handle photo uploads."""
    if queued_data:
        user_id = queued_data["user_id"]
        chat_id = queued_data["chat_id"]
        username = "QueuedUser"
    else:
        user = update.effective_user
        username = user.username
        user_id = user.id
        chat_id = update.effective_chat.id
    
    messages_to_delete = []
    user_mode_data = get_user_mode(user_id)
    
    # Skip checks if this is an auto-triggered queued task
    if not queued_data:
        # Auth check handled by decorator
        
        if is_on_cooldown(user_id):
            remaining = get_cooldown_remaining(user_id)
            await update.message.reply_text(
                f"⏳ **Please wait {remaining} seconds**\n\nYou can send another file after the cooldown.",
                parse_mode='Markdown'
            )
            return
            
        if user_mode_data["mode"] == "voice":
            await update.message.reply_text("❌ **Voice mode only works with videos!**")
            return
            
        if user_id in active_tasks:
            await update.message.reply_text("⚠️ You already have a file being processed.")
            return
            
        if is_server_busy():
            photo_obj = update.message.photo[-1]
            file_id = photo_obj.file_id
            file_size_mb = photo_obj.file_size / (1024 * 1024)
            metadata = {"mode": "face"}
            position = add_to_queue(user_id, chat_id, file_size_mb, file_id, "photo", metadata)
            wait_time = format_wait_time(estimate_wait_time(position, file_size_mb))
            
            queue_msg = await update.message.reply_text(
                f"⏳ **Server Busy - You are #{position} in Queue**\n"
                f"⏱️ Est. Wait: {wait_time}\n\n"
                f"✅ **Auto-Upload Active**\n"
                f"Your photo is saved. It will start automatically when it's your turn.\n"
                f"**You do NOT need to re-upload.**\n\n"
                f"❌ Use /stop to leave the queue.",
                parse_mode='Markdown'
            )
            add_to_queue(user_id, chat_id, file_size_mb, file_id, "photo", metadata, queue_msg.message_id)
            return
    
    remove_from_queue(user_id)
    
    if queued_data:
        file_id = queued_data["file_id"]
        file_size_mb = queued_data["file_size_mb"]
        file_name = "queued_photo.jpg"
        photo_obj = None
    else:
        photo_obj = update.message.photo[-1]
        file_id = photo_obj.file_id
        file_size_mb = photo_obj.file_size / (1024 * 1024)
        file_name = "photo.jpg"

    if not queued_data and (photo_obj.width > MAX_IMAGE_DIMENSION or photo_obj.height > MAX_IMAGE_DIMENSION):
        await update.message.reply_text("❌ Image resolution too high!")
        return
    
    if file_size_mb > MAX_IMAGE_SIZE_MB:
        msg = f"❌ Image too large ({file_size_mb:.1f} MB)!"
        if queued_data:
            await context.bot.send_message(chat_id=chat_id, text=msg)
        else:
            await update.message.reply_text(msg)
        return
    
    estimated_time = max(int(file_size_mb * ESTIMATE_IMAGE_SEC_PER_MB), 2)
    res_str = f"{photo_obj.width}x{photo_obj.height}" if photo_obj else "Saved Resolution"
    
    processing_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"⏳ **Processing your image...**\n\n📐 Resolution: {res_str}\n⏱️ Estimated time: ~{estimated_time}s",
        parse_mode='Markdown'
    )
    messages_to_delete.append(processing_msg.message_id)
    
    try:
        active_tasks[user_id] = {"type": "photo"}
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = os.path.join(temp_dir, "input.jpg")
            output_path = os.path.join(temp_dir, "output.jpg")
            file = await context.bot.get_file(file_id)
            await file.download_to_drive(input_path)
            
            success = await asyncio.to_thread(blur_faces_in_image, input_path, output_path)
            
            if success and os.path.exists(output_path):
                with open(output_path, 'rb') as f:
                    image_data = f.read()
                
                result_msg = await context.bot.send_document(
                    chat_id=chat_id,
                    document=BytesIO(image_data),
                    filename=f"blurred_{file_name}",
                    caption=f"✅ **Done!**\n⚠️ **SAVE NOW!** Auto-deleting in {AUTO_DELETE_SECONDS}s..."
                )
                messages_to_delete.append(result_msg.message_id)
                
                warning_msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🗑️ **Auto-delete in {AUTO_DELETE_SECONDS}s!**",
                    parse_mode='Markdown'
                )
                messages_to_delete.append(warning_msg.message_id)
                
                set_cooldown(user_id)
                asyncio.create_task(delete_messages_after_delay(context, chat_id, messages_to_delete, AUTO_DELETE_SECONDS))
            else:
                await context.bot.send_message(chat_id=chat_id, text="❌ Failed to process image.")
    except Exception as e:
        logger.error(f"Error processing photo: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"❌ An error occurred: {e}")
    finally:
        if user_id in active_tasks:
            del active_tasks[user_id]
        from handlers.queue_worker import trigger_next_queued_job
        asyncio.create_task(trigger_next_queued_job(context))


@require_auth
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE, queued_data: dict = None):
    """Handle document uploads."""
    from handlers.video import handle_video
    
    if queued_data:
        user_id = queued_data["user_id"]
        chat_id = queued_data["chat_id"]
        file_type = queued_data["file_type"]
    else:
        user = update.effective_user
        user_id = user.id
        chat_id = update.effective_chat.id
        document = update.message.document
        if not document or not document.mime_type:
            await update.message.reply_text("❌ Unsupported file type.")
            return
        mime_type = document.mime_type.lower()
        file_type = "document_video" if mime_type.startswith('video/') else ("document_photo" if mime_type.startswith('image/') else "unknown")

    if file_type == "document_video":
        await handle_video(update, context, queued_data=queued_data)
    elif file_type == "document_photo":
        # Check busy for documents
        if not queued_data and is_server_busy():
            document = update.message.document
            file_id = document.file_id
            file_size_mb = document.file_size / (1024 * 1024)
            metadata = {"mode": "face", "file_name": document.file_name}
            position = add_to_queue(user_id, chat_id, file_size_mb, file_id, "document_photo", metadata)
            wait_time = format_wait_time(estimate_wait_time(position, file_size_mb))
            queue_msg = await update.message.reply_text(
                f"⏳ **Server Busy - You are #{position} in Queue**\n"
                f"⏱️ Est. Wait: {wait_time}\n"
                f"✅ **Auto-Upload Active**\n"
                f"Your file is saved. It will start automatically when it's your turn.\n"
                f"**You do NOT need to re-upload.**\n\n"
                f"❌ Use /stop to leave the queue.",
                parse_mode='Markdown'
            )
            add_to_queue(user_id, chat_id, file_size_mb, file_id, "document_photo", metadata, queue_msg.message_id)
            return

        # Core document processing (similar to handle_photo)
        messages_to_delete = []
        if queued_data:
            file_id = queued_data["file_id"]
            file_size_mb = queued_data["file_size_mb"]
            file_name = queued_data["metadata"].get("file_name", "image.jpg")
        else:
            document = update.message.document
            file_id = document.file_id
            file_size_mb = document.file_size / (1024 * 1024)
            file_name = document.file_name or "image.jpg"

        processing_msg = await context.bot.send_message(chat_id=chat_id, text="⏳ **Processing image from document...**")
        messages_to_delete.append(processing_msg.message_id)

        try:
            active_tasks[user_id] = {"type": "document"}
            with tempfile.TemporaryDirectory() as temp_dir:
                ext = os.path.splitext(file_name)[1] or ".jpg"
                input_path = os.path.join(temp_dir, f"input{ext}")
                output_path = os.path.join(temp_dir, f"output{ext}")
                file = await context.bot.get_file(file_id)
                await file.download_to_drive(input_path)
                
                success = await asyncio.to_thread(blur_faces_in_image, input_path, output_path)
                
                if success and os.path.exists(output_path):
                    with open(output_path, 'rb') as f:
                        image_data = f.read()
                    
                    result_msg = await context.bot.send_document(
                        chat_id=chat_id,
                        document=BytesIO(image_data),
                        filename=f"blurred_{file_name}",
                        caption=f"✅ **Done!**\n⚠️ **SAVE NOW!** Auto-deleting in {AUTO_DELETE_SECONDS}s..."
                    )
                    messages_to_delete.append(result_msg.message_id)
                    set_cooldown(user_id)
                    asyncio.create_task(delete_messages_after_delay(context, chat_id, messages_to_delete, AUTO_DELETE_SECONDS))
                else:
                    await context.bot.send_message(chat_id=chat_id, text="❌ Failed to process document.")
        except Exception as e:
            logger.error(f"Error: {e}")
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Error: {e}")
        finally:
            if user_id in active_tasks:
                del active_tasks[user_id]
            from handlers.queue_worker import trigger_next_queued_job
            asyncio.create_task(trigger_next_queued_job(context))
    else:
        await update.message.reply_text("❌ Unsupported file type.")


@require_auth
async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle unknown messages."""
    await update.message.reply_text("📤 Please send me a **video** or **image** to process.")
