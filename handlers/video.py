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
    get_queue_position,
    estimate_wait_time,
    format_wait_time,
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


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle video uploads - routes to face blur or voice anonymization based on mode."""
    user = update.effective_user
    username = user.username
    user_id = user.id
    chat_id = update.effective_chat.id
    
    messages_to_delete = []
    
    is_allowed, message = is_user_allowed(username, user_id)
    if not is_allowed:
        await update.message.reply_text(message)
        return
    
    # Check cooldown (30 seconds after last processed file)
    if is_on_cooldown(user_id):
        remaining = get_cooldown_remaining(user_id)
        await update.message.reply_text(
            f"⏳ **Please wait {remaining} seconds**\n\n"
            f"You can send another file after the cooldown period.",
            parse_mode='Markdown'
        )
        return
    
    # Check if user already has an active task
    if user_id in active_tasks:
        await update.message.reply_text(
            "⚠️ You already have a file being processed.\n\n"
            "Use /stop to cancel it, or wait for it to finish."
        )
        return
    
    # Check if server is busy (2 concurrent jobs max)
    if is_server_busy():
        # Get file info first for queue
        video = update.message.video or update.message.document
        if not video:
            await update.message.reply_text("❌ No video detected. Please send a valid video file.")
            return
        
        file_size_mb = video.file_size / (1024 * 1024)
        position = add_to_queue(user_id, chat_id, file_size_mb)
        wait_time = format_wait_time(estimate_wait_time(position, file_size_mb))
        
        await update.message.reply_text(
            f"⏳ **Server Busy - You're #{position} in queue**\n\n"
            f"📊 Estimated wait: {wait_time}\n\n"
            f"⚠️ **Please re-send your file when notified.**\n"
            f"We'll message you when a slot opens.\n\n"
            f"Use /stop to leave the queue.",
            parse_mode='Markdown'
        )
        return
    
    video = update.message.video or update.message.document
    
    if not video:
        await update.message.reply_text("❌ No video detected. Please send a valid video file.")
        return
    
    # Check file size
    file_size_mb = video.file_size / (1024 * 1024)
    
    if file_size_mb > MAX_VIDEO_SIZE_MB:
        await update.message.reply_text(
            f"❌ Video too large!\n\n"
            f"Your file: {file_size_mb:.1f} MB\n"
            f"Maximum: {MAX_VIDEO_SIZE_MB} MB"
        )
        return
    
    # Check duration (if available)
    if hasattr(video, 'duration') and video.duration:
        if video.duration > MAX_VIDEO_DURATION_SECONDS:
            await update.message.reply_text(
                f"❌ Video too long!\n\n"
                f"Your video: {video.duration} seconds\n"
                f"Maximum: {MAX_VIDEO_DURATION_SECONDS} seconds"
            )
            return
    
    # Get user's current mode
    user_settings = get_user_mode(user_id)
    current_mode = user_settings["mode"]
    
    # Route based on mode
    if current_mode == "face":
        await process_face_blur(update, context, video, file_size_mb, messages_to_delete, chat_id, user_id)
    else:  # voice mode
        await process_voice_anon(update, context, video, file_size_mb, messages_to_delete, chat_id, user_id)


async def process_face_blur(update, context, video, file_size_mb, messages_to_delete, chat_id, user_id):
    """Process video for face blurring."""
    estimated_time = int(file_size_mb * ESTIMATE_VIDEO_SEC_PER_MB)
    estimated_time = max(estimated_time, 5)
    
    processing_msg = await update.message.reply_text(
        f"🎭 **Face Blur Mode**\n\n"
        f"⏳ Processing your video...\n"
        f"📊 File size: {file_size_mb:.1f} MB\n"
        f"⏱️ Estimated time: ~{estimated_time} seconds\n\n"
        f"Use /stop to cancel.",
        parse_mode='Markdown'
    )
    messages_to_delete.append(processing_msg.message_id)
    
    temp_dir = None
    cancel_event = threading.Event()
    
    try:
        temp_dir = tempfile.mkdtemp()
        
        active_tasks[user_id] = {
            "temp_dir": temp_dir,
            "cancel_event": cancel_event,
            "type": "video_face"
        }
        
        file_name = video.file_name if hasattr(video, 'file_name') and video.file_name else "video.mp4"
        ext = os.path.splitext(file_name)[1] or ".mp4"
        
        input_path = os.path.join(temp_dir, f"input{ext}")
        output_path = os.path.join(temp_dir, "output.mp4")
        
        file = await context.bot.get_file(video.file_id)
        await file.download_to_drive(input_path)
        
        if cancel_event.is_set():
            abort_msg = await update.message.reply_text(
                "🛑 **Processing aborted!**\n\nAll files have been cleaned up.",
                parse_mode='Markdown'
            )
            messages_to_delete.append(abort_msg.message_id)
            return
        
        success, was_cancelled = await asyncio.to_thread(
            blur_faces_in_video, input_path, output_path, 2, cancel_event.is_set
        )
        
        if was_cancelled:
            abort_msg = await update.message.reply_text(
                "🛑 **Processing aborted!**\n\nAll files have been cleaned up.\n\n📤 Send another file when you're ready.",
                parse_mode='Markdown'
            )
            messages_to_delete.append(abort_msg.message_id)
            return
        
        if success and os.path.exists(output_path):
            with open(output_path, 'rb') as f:
                video_data = f.read()
            
            result_msg = await update.message.reply_document(
                document=BytesIO(video_data),
                filename=f"blurred_{os.path.splitext(file_name)[0]}.mp4",
                caption=f"✅ **Done!** Faces blurred.\n\n"
                        f"⚠️ **SAVE NOW!** Auto-deleting in {AUTO_DELETE_SECONDS} seconds..."
            )
            messages_to_delete.append(result_msg.message_id)
            
            warning_msg = await update.message.reply_text(
                f"🗑️ **Auto-delete in {AUTO_DELETE_SECONDS} seconds!**\n\n"
                f"📥 Save the video above NOW!\n"
                f"🔒 All bot messages will be deleted.\n\n"
                f"⚠️ Please also delete your original file manually.",
                parse_mode='Markdown'
            )
            messages_to_delete.append(warning_msg.message_id)
            
            # Set cooldown after successful processing
            set_cooldown(user_id)
            
            asyncio.create_task(
                delete_messages_after_delay(context, chat_id, messages_to_delete, AUTO_DELETE_SECONDS)
            )
        else:
            error_msg = await update.message.reply_text(
                "❌ Failed to process video. Please try again.\n\n📤 Send another file to try again."
            )
            messages_to_delete.append(error_msg.message_id)
    
    except Exception as e:
        logger.error(f"Error processing video (face blur): {e}")
        error_msg = await update.message.reply_text(f"❌ An error occurred: {str(e)}")
        messages_to_delete.append(error_msg.message_id)
    
    finally:
        if user_id in active_tasks:
            del active_tasks[user_id]
        
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except:
                pass


async def process_voice_anon(update, context, video, file_size_mb, messages_to_delete, chat_id, user_id):
    """Process video for voice anonymization - shows level selection first."""
    
    # Store video info in context for callback
    context.user_data['pending_voice_video'] = {
        'video': video,
        'file_size_mb': file_size_mb,
        'messages_to_delete': messages_to_delete,
    }
    
    # Show voice level selection
    keyboard = [
        [
            InlineKeyboardButton("⚡ Fast (~15s)", callback_data="voice_fast"),
            InlineKeyboardButton("🔒 Secure (~2min)", callback_data="voice_secure"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    level_msg = await update.message.reply_text(
        "🔊 **Voice Anonymize Mode**\n\n"
        "Choose security level:\n\n"
        "⚡ **Fast** - Pitch/tempo shift (~80% security)\n"
        "🔒 **Secure** - Enhanced processing (~90% security)\n\n"
        f"📊 File size: {file_size_mb:.1f} MB",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    messages_to_delete.append(level_msg.message_id)
    context.user_data['pending_voice_video']['level_msg_id'] = level_msg.message_id


async def voice_level_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback when user selects voice anonymization level."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    username = query.from_user.username
    chat_id = query.message.chat_id
    callback_data = query.data
    
    # Auth check
    is_allowed, message = is_user_allowed(username, user_id)
    if not is_allowed:
        await query.edit_message_text(message)
        return
    
    # Get pending video info
    pending = context.user_data.get('pending_voice_video')
    if not pending:
        await query.edit_message_text("❌ Session expired. Please send the video again.")
        return
    
    video = pending['video']
    file_size_mb = pending['file_size_mb']
    messages_to_delete = pending['messages_to_delete']
    
    # Determine which mode
    is_secure = callback_data == "voice_secure"
    mode_name = "Secure" if is_secure else "Fast"
    estimated_time = "2-3 minutes" if is_secure else "~15 seconds"
    
    # Update message
    await query.edit_message_text(
        f"🔊 **Voice Anonymize ({mode_name})**\n\n"
        f"⏳ Processing your video...\n"
        f"📊 File size: {file_size_mb:.1f} MB\n"
        f"⏱️ Estimated time: {estimated_time}\n\n"
        f"Use /stop to cancel.",
        parse_mode='Markdown'
    )
    
    temp_dir = None
    cancel_event = threading.Event()
    
    try:
        temp_dir = tempfile.mkdtemp()
        
        active_tasks[user_id] = {
            "temp_dir": temp_dir,
            "cancel_event": cancel_event,
            "type": f"video_voice_{mode_name.lower()}"
        }
        
        file_name = video.file_name if hasattr(video, 'file_name') and video.file_name else "video.mp4"
        ext = os.path.splitext(file_name)[1] or ".mp4"
        
        input_path = os.path.join(temp_dir, f"input{ext}")
        output_path = os.path.join(temp_dir, "output.mp4")
        
        # Download file
        file = await context.bot.get_file(video.file_id)
        await file.download_to_drive(input_path)
        
        if cancel_event.is_set():
            await query.edit_message_text(
                "🛑 **Processing aborted!**\n\nAll files have been cleaned up.",
                parse_mode='Markdown'
            )
            return
        
        # Process based on selected level
        if is_secure:
            success, was_cancelled = await asyncio.to_thread(
                anonymize_voice_secure, input_path, output_path, cancel_event.is_set
            )
        else:
            success, was_cancelled = await asyncio.to_thread(
                anonymize_voice_fast, input_path, output_path, cancel_event.is_set
            )
        
        if was_cancelled:
            await query.edit_message_text(
                "🛑 **Processing aborted!**\n\nAll files have been cleaned up.\n\n📤 Send another file when you're ready.",
                parse_mode='Markdown'
            )
            return
        
        if success and os.path.exists(output_path):
            with open(output_path, 'rb') as f:
                video_data = f.read()
            
            result_msg = await context.bot.send_document(
                chat_id=chat_id,
                document=BytesIO(video_data),
                filename=f"anon_{os.path.splitext(file_name)[0]}.mp4",
                caption=f"✅ **Done!** Voice anonymized ({mode_name}).\n\n"
                        f"⚠️ **SAVE NOW!** Auto-deleting in {AUTO_DELETE_SECONDS} seconds..."
            )
            messages_to_delete.append(result_msg.message_id)
            
            warning_msg = await context.bot.send_message(
                chat_id=chat_id,
                text=f"🗑️ **Auto-delete in {AUTO_DELETE_SECONDS} seconds!**\n\n"
                     f"📥 Save the video above NOW!\n"
                     f"🔒 All bot messages will be deleted.\n\n"
                     f"⚠️ Please also delete your original file manually.",
                parse_mode='Markdown'
            )
            messages_to_delete.append(warning_msg.message_id)
            
            # Set cooldown after successful processing
            set_cooldown(user_id)
            
            asyncio.create_task(
                delete_messages_after_delay(context, chat_id, messages_to_delete, AUTO_DELETE_SECONDS)
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ Failed to process video. Please try again.\n\n📤 Send another file to try again."
            )
    
    except Exception as e:
        logger.error(f"Error processing video (voice anon): {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"❌ An error occurred: {str(e)}")
    
    finally:
        if user_id in active_tasks:
            del active_tasks[user_id]
        
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except:
                pass
        
        # Clean up pending video data
        if 'pending_voice_video' in context.user_data:
            del context.user_data['pending_voice_video']
