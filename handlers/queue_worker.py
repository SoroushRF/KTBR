"""
KTBR - Queue Worker
Handles automatic processing of queued files.
"""

import asyncio
from telegram.ext import ContextTypes
from utils.queue_manager import notify_next_in_queue, remove_from_queue
from utils import logger


async def trigger_next_queued_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Check if a slot is available and start processing the next user in queue.
    """
    # Notify next user and get their data
    next_user = await notify_next_in_queue(context)
    
    if not next_user:
        return
        
    user_id = next_user["user_id"]
    chat_id = next_user["chat_id"]
    file_type = next_user["file_type"]
    
    logger.info(f"Auto-triggering processing for user {user_id} ({file_type})")
    
    # Lazy import to avoid circular dependencies
    from handlers.video import handle_video
    from handlers.photo import handle_photo, handle_document
    
    # We pass 'None' as update because handlers only use update to get user info,
    # and we provide that via 'queued_data'.
    
    try:
        if file_type == "video":
            await handle_video(None, context, queued_data=next_user)
        elif file_type == "photo":
            await handle_photo(None, context, queued_data=next_user)
        elif file_type.startswith("document"):
            await handle_document(None, context, queued_data=next_user)
        else:
            logger.error(f"Unknown file type in queue: {file_type}")
            remove_from_queue(user_id)
            
    except Exception as e:
        logger.error(f"Error in auto-worker for user {user_id}: {e}")
        remove_from_queue(user_id)
