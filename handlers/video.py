"""
KTBR - Video Handler
Handles video uploads and processing.
"""

import os
import asyncio
import tempfile
import shutil
import threading
from io import BytesIO

from telegram import Update
from telegram.ext import ContextTypes

from config import (
    MAX_VIDEO_DURATION_SECONDS,
    MAX_VIDEO_SIZE_MB,
    ESTIMATE_VIDEO_SEC_PER_MB,
    active_tasks,
    logger
)
from utils.auth import is_user_allowed
from processors.face_blur import blur_faces_in_video


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle video uploads."""
    user = update.effective_user
    username = user.username
    user_id = user.id
    
    is_allowed, message = is_user_allowed(username, user_id)
    if not is_allowed:
        await update.message.reply_text(message)
        return
    
    # Check if user already has an active task
    if user_id in active_tasks:
        await update.message.reply_text(
            "⚠️ You already have a file being processed.\n\n"
            "Use /stop to cancel it, or wait for it to finish."
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
    
    # Estimate processing time
    estimated_time = int(file_size_mb * ESTIMATE_VIDEO_SEC_PER_MB)
    estimated_time = max(estimated_time, 5)
    
    await update.message.reply_text(
        f"⏳ **Processing your video...**\n\n"
        f"📊 File size: {file_size_mb:.1f} MB\n"
        f"⏱️ Estimated time: ~{estimated_time} seconds\n\n"
        f"Use /stop to cancel.\n"
        f"Please wait...",
        parse_mode='Markdown'
    )
    
    # Download and process
    temp_dir = None
    cancel_event = threading.Event()
    
    try:
        temp_dir = tempfile.mkdtemp()
        
        # Register active task with the cancel event
        active_tasks[user_id] = {
            "temp_dir": temp_dir,
            "cancel_event": cancel_event,
            "type": "video"
        }
        
        # Get file extension
        file_name = video.file_name if hasattr(video, 'file_name') and video.file_name else "video.mp4"
        ext = os.path.splitext(file_name)[1] or ".mp4"
        
        input_path = os.path.join(temp_dir, f"input{ext}")
        output_path = os.path.join(temp_dir, "output.mp4")
        
        # Download file
        file = await context.bot.get_file(video.file_id)
        await file.download_to_drive(input_path)
        
        # Check if cancelled during download
        if cancel_event.is_set():
            await update.message.reply_text(
                "🛑 **Processing aborted!**\n\n"
                "All files have been cleaned up.",
                parse_mode='Markdown'
            )
            return
        
        # Process video in background thread
        success, was_cancelled = await asyncio.to_thread(
            blur_faces_in_video, input_path, output_path, 2, cancel_event.is_set
        )
        
        # If cancelled during processing, send abort message
        if was_cancelled:
            await update.message.reply_text(
                "🛑 **Processing aborted!**\n\n"
                "All files have been cleaned up.\n\n"
                "📤 Send another file when you're ready.",
                parse_mode='Markdown'
            )
            return
        
        if success and os.path.exists(output_path):
            with open(output_path, 'rb') as f:
                video_data = f.read()
            
            await update.message.reply_document(
                document=BytesIO(video_data),
                filename=f"blurred_{os.path.splitext(file_name)[0]}.mp4",
                caption="✅ **Done!** Here's your processed video with blurred faces."
            )
            await update.message.reply_text(
                "📤 Send another **video** or **image** to blur faces.",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("❌ Failed to process video. Please try again.\n\n📤 Send another file to try again.")
    
    except Exception as e:
        logger.error(f"Error processing video: {e}")
        await update.message.reply_text(f"❌ An error occurred: {str(e)}")
    
    finally:
        if user_id in active_tasks:
            del active_tasks[user_id]
        
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except:
                pass
