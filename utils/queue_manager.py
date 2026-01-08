"""
KTBR - Queue Manager
Handles processing queue and user cooldowns.
"""

import time
import asyncio
from config import (
    MAX_CONCURRENT_JOBS,
    processing_queue,
    COOLDOWN_SECONDS,
    user_cooldowns,
    active_tasks,
    ESTIMATE_VIDEO_SEC_PER_MB,
    logger
)


# =============================================================================
# QUEUE MANAGEMENT
# =============================================================================

def get_active_job_count() -> int:
    """Get the number of currently processing jobs."""
    return len(active_tasks)


def is_server_busy() -> bool:
    """Check if server is at maximum capacity."""
    return get_active_job_count() >= MAX_CONCURRENT_JOBS


def get_queue_length() -> int:
    """Get the number of users waiting in queue."""
    return len(processing_queue)


def get_queue_position(user_id: int) -> int:
    """
    Get user's position in queue (1-indexed).
    Returns 0 if not in queue.
    """
    for i, entry in enumerate(processing_queue):
        if entry["user_id"] == user_id:
            return i + 1
    return 0


def is_in_queue(user_id: int) -> bool:
    """Check if user is already in the queue."""
    return get_queue_position(user_id) > 0


def add_to_queue(user_id: int, chat_id: int, file_size_mb: float, file_id: str, file_type: str, metadata: dict, queue_msg_id: int = None) -> int:
    """
    Add user to the processing queue with file metadata.
    Returns their position (1-indexed).
    """
    # If already in queue, update their data
    for item in processing_queue:
        if item["user_id"] == user_id:
            item["file_size_mb"] = file_size_mb
            item["file_id"] = file_id
            item["file_type"] = file_type
            item["metadata"] = metadata
            if queue_msg_id:
                item["queue_msg_id"] = queue_msg_id
            return get_queue_position(user_id)
    
    entry = {
        "user_id": user_id,
        "chat_id": chat_id,
        "timestamp": time.time(),
        "file_size_mb": file_size_mb,
        "file_id": file_id,
        "file_type": file_type,
        "metadata": metadata, # user mode, etc
        "queue_msg_id": queue_msg_id
    }
    processing_queue.append(entry)
    position = len(processing_queue)
    logger.info(f"User {user_id} added to queue at position {position} with file {file_id}")
    return position


def remove_from_queue(user_id: int) -> bool:
    """
    Remove user from the queue.
    Returns True if removed, False if not found.
    """
    global processing_queue
    for i, entry in enumerate(processing_queue):
        if entry["user_id"] == user_id:
            processing_queue.pop(i)
            logger.info(f"User {user_id} removed from queue")
            return True
    return False


def get_next_in_queue() -> dict | None:
    """
    Get the next user in queue (first in line).
    Returns None if queue is empty.
    Does NOT remove from queue - call remove_from_queue separately.
    """
    if processing_queue:
        return processing_queue[0]
    return None


def estimate_wait_time(position: int, avg_file_size_mb: float = 10) -> int:
    """
    Estimate wait time in seconds based on queue position.
    
    Args:
        position: Position in queue (1-indexed)
        avg_file_size_mb: Average file size for estimation
    
    Returns:
        Estimated wait time in seconds
    """
    if position <= 0:
        return 0
    
    # Estimate based on:
    # - Current jobs finishing (avg half done)
    # - Jobs ahead in queue
    
    avg_job_time = avg_file_size_mb * ESTIMATE_VIDEO_SEC_PER_MB
    
    # Current jobs: estimate half remaining
    current_jobs_time = (get_active_job_count() * avg_job_time) / 2
    
    # Queue jobs ahead of this position
    jobs_ahead = position - 1
    queue_time = jobs_ahead * avg_job_time
    
    total_wait = current_jobs_time + queue_time
    return int(total_wait)


def format_wait_time(seconds: int) -> str:
    """Format wait time as human-readable string."""
    if seconds < 60:
        return f"~{seconds} seconds"
    else:
        minutes = seconds // 60
        return f"~{minutes} minute{'s' if minutes > 1 else ''}"


# =============================================================================
# COOLDOWN MANAGEMENT
# =============================================================================

def set_cooldown(user_id: int) -> None:
    """Set cooldown for a user (called after they receive processed media)."""
    cooldown_ends = time.time() + COOLDOWN_SECONDS
    user_cooldowns[user_id] = cooldown_ends
    logger.info(f"Cooldown set for user {user_id} (ends in {COOLDOWN_SECONDS}s)")


def is_on_cooldown(user_id: int) -> bool:
    """Check if user is currently on cooldown."""
    if user_id not in user_cooldowns:
        return False
    
    if time.time() >= user_cooldowns[user_id]:
        # Cooldown expired, clean up
        del user_cooldowns[user_id]
        return False
    
    return True


def get_cooldown_remaining(user_id: int) -> int:
    """Get remaining cooldown time in seconds. Returns 0 if not on cooldown."""
    if user_id not in user_cooldowns:
        return 0
    
    remaining = user_cooldowns[user_id] - time.time()
    if remaining <= 0:
        # Cooldown expired, clean up
        del user_cooldowns[user_id]
        return 0
    
    return int(remaining)


def clear_cooldown(user_id: int) -> None:
    """Clear cooldown for a user (admin function)."""
    if user_id in user_cooldowns:
        del user_cooldowns[user_id]
        logger.info(f"Cooldown cleared for user {user_id}")


# =============================================================================
# STATUS HELPERS
# =============================================================================

def get_server_status() -> dict:
    """Get current server status for debugging/monitoring."""
    return {
        "active_jobs": get_active_job_count(),
        "max_jobs": MAX_CONCURRENT_JOBS,
        "queue_length": get_queue_length(),
        "is_busy": is_server_busy(),
        "cooldowns_active": len(user_cooldowns)
    }


async def update_all_queue_messages(context) -> None:
    """
    Iterate through the queue and update everyone's position and ETA message.
    """
    for i, entry in enumerate(processing_queue):
        user_id = entry["user_id"]
        chat_id = entry["chat_id"]
        msg_id = entry.get("queue_msg_id")
        
        if not msg_id:
            continue
            
        position = i + 1
        wait_time = format_wait_time(estimate_wait_time(position, entry["file_size_mb"]))
        
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=f"⏳ **Queue Update - You're now #{position}**\n"
                     f"⏱️ Est. Wait: {wait_time}\n\n"
                     f"✅ **Auto-Upload Active**\n"
                     f"Your file is saved. It will start automatically when it's your turn.\n"
                     f"**You do NOT need to re-upload.**\n\n"
                     f"❌ Use /stop to leave the queue.",
                parse_mode='Markdown'
            )
        except Exception as e:
            # If message can't be edited (e.g. deleted), it's fine
            logger.debug(f"Could not update queue message for {user_id}: {e}")


async def notify_next_in_queue(context) -> dict | None:
    """
    Check if a slot is open and notify the next user.
    Also updates everyone else's queue position.
    Returns the next_user object if notified, else None.
    """
    # First update everyone still in line
    await update_all_queue_messages(context)
    
    if is_server_busy():
        return None
        
    next_user = get_next_in_queue()
    if not next_user:
        return None
        
    chat_id = next_user["chat_id"]
    user_id = next_user["user_id"]
    
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ **It's your turn!**\n\n"
                 f"Processing has started automatically.\n"
                 f"**Please do NOT send the file again.**",
            parse_mode='Markdown'
        )
        logger.info(f"Auto-notified user {user_id} of their turn")
        return next_user
    except Exception as e:
        logger.error(f"Failed to notify user {user_id}: {e}")
        remove_from_queue(user_id)
        return None
