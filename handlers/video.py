"""
KTBR - Video Handler
Handles video uploads and processing with auto-delete.
Supports both Face Blur and Voice Anonymize modes.
"""

import os
import asyncio
import tempfile
import shutil
import threading
from io import BytesIO

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import (
    MAX_VIDEO_DURATION_SECONDS,
    MAX_VIDEO_SIZE_MB,
    ESTIMATE_VIDEO_SEC_PER_MB,
    AUTO_DELETE_SECONDS,
    active_tasks,
    user_modes,
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
from processors.face_blur import blur_faces_in_video
from processors.voice_anon import anonymize_voice_fast, anonymize_voice_secure


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


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE, queued_data: dict = None):
    """Handle video uploads."""
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
    user_settings = get_user_mode(user_id)
    current_mode = user_settings["mode"]
    voice_level = user_settings["voice_level"]
    
    # Skip checks if this is an auto-triggered queued task
    if not queued_data:
        is_allowed, message = is_user_allowed(username, user_id)
        if not is_allowed:
            await update.message.reply_text(message)
            return
        
        if is_on_cooldown(user_id):
            remaining = get_cooldown_remaining(user_id)
            await update.message.reply_text(f"⏳ **Please wait {remaining}s**")
            return
            
        if user_id in active_tasks:
            await update.message.reply_text("⚠️ Active task already running.")
            return
            
        if is_server_busy():
            video_obj = update.message.video or update.message.document
            if not video_obj: return
            
            file_id = video_obj.file_id
            file_type = "video" if update.message.video else "document_video"
            file_size_mb = video_obj.file_size / (1024 * 1024)
            metadata = {"mode": current_mode, "voice_level": voice_level}
            position = add_to_queue(user_id, chat_id, file_size_mb, file_id, file_type, metadata)
            wait_time = format_wait_time(estimate_wait_time(position, file_size_mb))
            
            queue_msg = await update.message.reply_text(
                f"⏳ **Server Busy - You are #{position} in Queue**\n"
                f"⏱️ Est. Wait: {wait_time}\n\n"
                f"✅ **Auto-Upload Active**\n"
                f"Your file is saved. It will start automatically when it's your turn.\n"
                f"**You do NOT need to re-upload.**\n\n"
                f"❌ Use /stop to leave the queue.",
                parse_mode='Markdown'
            )
            add_to_queue(user_id, chat_id, file_size_mb, file_id, file_type, metadata, queue_msg.message_id)
            return
    
    remove_from_queue(user_id)
    
    if queued_data:
        file_id = queued_data["file_id"]
        file_size_mb = queued_data["file_size_mb"]
        current_mode = queued_data["metadata"]["mode"]
        voice_level = queued_data["metadata"]["voice_level"]
        file_name = "queued_video.mp4"
        video_obj = None
    else:
        video_obj = update.message.video or update.message.document
        if not video_obj: return
        file_id = video_obj.file_id
        file_size_mb = video_obj.file_size / (1024 * 1024)
        file_name = video_obj.file_name if hasattr(video_obj, 'file_name') and video_obj.file_name else "video.mp4"

    if file_size_mb > MAX_VIDEO_SIZE_MB:
        msg = f"❌ Too large ({file_size_mb:.1f} MB)"
        if queued_data: await context.bot.send_message(chat_id=chat_id, text=msg)
        else: await update.message.reply_text(msg)
        return
    
    # Duration check (normal only)
    if video_obj and hasattr(video_obj, 'duration') and video_obj.duration > MAX_VIDEO_DURATION_SECONDS:
        await update.message.reply_text(f"❌ Too long ({video_obj.duration}s)")
        return
    
    if current_mode == "face":
        await start_face_blur(context, chat_id, user_id, file_id, file_name, file_size_mb, messages_to_delete)
    else:
        if queued_data:
            await start_voice_processing(context, chat_id, user_id, file_id, file_name, file_size_mb, messages_to_delete, voice_level == "secure")
        else:
            await show_voice_selection(update, context, video_obj, file_size_mb, messages_to_delete)


async def start_face_blur(context, chat_id, user_id, file_id, file_name, file_size_mb, messages_to_delete):
    """Core face blur processing."""
    estimated_time = max(int(file_size_mb * ESTIMATE_VIDEO_SEC_PER_MB), 5)
    processing_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"🎭 **Face Blur**\n⏳ Processing... (~{estimated_time}s)",
        parse_mode='Markdown'
    )
    messages_to_delete.append(processing_msg.message_id)
    
    temp_dir = tempfile.mkdtemp()
    cancel_event = threading.Event()
    active_tasks[user_id] = {"temp_dir": temp_dir, "cancel_event": cancel_event, "type": "video_face"}
    
    try:
        ext = os.path.splitext(file_name)[1] or ".mp4"
        input_path = os.path.join(temp_dir, f"input{ext}")
        output_path = os.path.join(temp_dir, "output.mp4")
        
        file = await context.bot.get_file(file_id)
        await file.download_to_drive(input_path)
        
        success, cancelled = await asyncio.to_thread(blur_faces_in_video, input_path, output_path, 2, cancel_event.is_set)
        
        if success and not cancelled and os.path.exists(output_path):
            with open(output_path, 'rb') as f: video_data = f.read()
            await context.bot.send_document(
                chat_id=chat_id,
                document=BytesIO(video_data),
                filename=f"blurred_{file_name}",
                caption=f"✅ Done!\n⚠️ Saving now! Deleting in {AUTO_DELETE_SECONDS}s"
            )
            set_cooldown(user_id)
            asyncio.create_task(delete_messages_after_delay(context, chat_id, messages_to_delete, AUTO_DELETE_SECONDS))
        else:
            await context.bot.send_message(chat_id=chat_id, text="❌ Failed/Aborted")
    except Exception as e:
        logger.error(f"Error: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Error: {e}")
    finally:
        if user_id in active_tasks: del active_tasks[user_id]
        shutil.rmtree(temp_dir, ignore_errors=True)
        from handlers.queue_worker import trigger_next_queued_job
        asyncio.create_task(trigger_next_queued_job(context))


async def show_voice_selection(update, context, video, file_size_mb, messages_to_delete):
    """Show inline keyboard for voice level."""
    context.user_data['pending_voice_video'] = {'file_id': video.file_id, 'file_name': video.file_name, 'file_size_mb': file_size_mb, 'messages_to_delete': messages_to_delete}
    keyboard = [[InlineKeyboardButton("⚡ Fast", callback_data="voice_fast"), InlineKeyboardButton("🔒 Secure", callback_data="voice_secure")]]
    await update.message.reply_text("🔊 **Voice Mode**\nChoose Level:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


async def voice_level_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voice level selection."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    pending = context.user_data.get('pending_voice_video')
    if not pending: return
    
    is_secure = query.data == "voice_secure"
    await query.edit_message_text(f"🔊 **Voice Mode ({'Secure' if is_secure else 'Fast'})**\n⏳ Starting...")
    
    await start_voice_processing(
        context, query.message.chat_id, user_id, 
        pending['file_id'], pending['file_name'], pending['file_size_mb'], 
        pending['messages_to_delete'], is_secure
    )


async def start_voice_processing(context, chat_id, user_id, file_id, file_name, file_size_mb, messages_to_delete, is_secure):
    """Core voice processing."""
    mode_name = "Secure" if is_secure else "Fast"
    processing_msg = await context.bot.send_message(chat_id=chat_id, text=f"🔊 **Voice Anon ({mode_name})**\n⏳ Processing...")
    messages_to_delete.append(processing_msg.message_id)
    
    temp_dir = tempfile.mkdtemp()
    cancel_event = threading.Event()
    active_tasks[user_id] = {"temp_dir": temp_dir, "cancel_event": cancel_event, "type": "video_voice"}
    
    try:
        ext = os.path.splitext(file_name or "video.mp4")[1] or ".mp4"
        input_path = os.path.join(temp_dir, f"input{ext}")
        output_path = os.path.join(temp_dir, "output.mp4")
        
        file = await context.bot.get_file(file_id)
        await file.download_to_drive(input_path)
        
        proc_func = anonymize_voice_secure if is_secure else anonymize_voice_fast
        success, cancelled = await asyncio.to_thread(proc_func, input_path, output_path, cancel_event.is_set)
        
        if success and not cancelled:
            with open(output_path, 'rb') as f: data = f.read()
            await context.bot.send_document(chat_id=chat_id, document=BytesIO(data), filename=f"anon_{file_name}", caption=f"✅ Voice Anonymized ({mode_name})")
            set_cooldown(user_id)
            asyncio.create_task(delete_messages_after_delay(context, chat_id, messages_to_delete, AUTO_DELETE_SECONDS))
        else:
            await context.bot.send_message(chat_id=chat_id, text="❌ Failed")
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        if user_id in active_tasks: del active_tasks[user_id]
        shutil.rmtree(temp_dir, ignore_errors=True)
        from handlers.queue_worker import trigger_next_queued_job
        asyncio.create_task(trigger_next_queued_job(context))
