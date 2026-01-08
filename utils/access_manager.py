"""
KTBR - Access Request Manager
Handles persistence of pending access requests.
"""

import json
import os
import time
from config import PENDING_REQUESTS_FILE, logger

# Request Statuses
STATUS_PENDING = "pending"
STATUS_IGNORED = "ignored"

def load_pending_requests() -> dict:
    """
    Load pending requests from JSON file.
    structure: { "user_id": { "first_name": str, "username": str, "note": str, "status": str, "timestamp": float } }
    """
    if os.path.exists(PENDING_REQUESTS_FILE):
        try:
            with open(PENDING_REQUESTS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load pending requests: {e}")
            return {}
    return {}

def save_pending_requests(data: dict):
    """Save pending requests to JSON file."""
    try:
        with open(PENDING_REQUESTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save pending requests: {e}")

def add_request(user_id: int, first_name: str, username: str, note: str):
    """Add a new access request."""
    data = load_pending_requests()
    data[str(user_id)] = {
        "first_name": first_name,
        "username": username,
        "note": note,
        "status": STATUS_PENDING,
        "timestamp": time.time()
    }
    save_pending_requests(data)
    logger.info(f"New access request saved for user {user_id}")

def get_request_status(user_id: int) -> str:
    """
    Get status of a user's request.
    Returns: 'pending', 'ignored', or None (no request found)
    """
    data = load_pending_requests()
    record = data.get(str(user_id))
    if record:
        return record.get("status")
    return None

def mark_ignored(user_id: int):
    """Mark a request as ignored/silently denied."""
    data = load_pending_requests()
    str_id = str(user_id)
    if str_id in data:
        data[str_id]["status"] = STATUS_IGNORED
        save_pending_requests(data)
        logger.info(f"Access request for user {user_id} marked as ignored.")

def remove_request(user_id: int):
    """Remove a request (e.g. after approval)."""
    data = load_pending_requests()
    str_id = str(user_id)
    if str_id in data:
        del data[str_id]
        save_pending_requests(data)
