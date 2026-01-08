"""
KTBR - Queue Manager
Handles processing queue and user cooldowns.
"""

import time
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


def add_to_queue(user_id: int, chat_id: int, file_size_mb: float = 0) -> int:
    """
    Add user to the processing queue.
    Returns their position (1-indexed).
    """
    # Don't add if already in queue
    if is_in_queue(user_id):
        return get_queue_position(user_id)
    
    entry = {
        "user_id": user_id,
        "chat_id": chat_id,
        "timestamp": time.time(),
        "file_size_mb": file_size_mb
    }
    processing_queue.append(entry)
    position = len(processing_queue)
    logger.info(f"User {user_id} added to queue at position {position}")
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


async def notify_next_in_queue(context) -> bool:
    """
    Check if a slot is open and notify the next user in the queue.
    Called when a processing job finishes.
    """
    if is_server_busy():
        return False
        
    next_user = get_next_in_queue()
    if not next_user:
        return False
        
    chat_id = next_user["chat_id"]
    user_id = next_user["user_id"]
    
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ **A slot is now open!**\n\n"
                 f"It's your turn. You can now send your video or photo for processing.\n\n"
                 f"⚠️ *Note: Others in queue can also see this, so send your file soon!*",
            parse_mode='Markdown'
        )
        logger.info(f"Notified user {user_id} that slot is open")
        return True
    except Exception as e:
        logger.error(f"Failed to notify user {user_id}: {e}")
        # If notification fails, maybe they blocked the bot - remove them to avoid blocking queue
        remove_from_queue(user_id)
        return False
