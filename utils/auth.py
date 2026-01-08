"""
KTBR - User Authorization Utilities
Handles whitelist-based access control.
"""

import json
import os
from config import ALLOWED_USERNAMES, AUTHORIZED_IDS_FILE, OWNER_ID, logger


def load_authorized_ids() -> list:
    """Load list of authorized user IDs."""
    if os.path.exists(AUTHORIZED_IDS_FILE):
        try:
            with open(AUTHORIZED_IDS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load authorized IDs: {e}")
            return []
    return []



def save_authorized_ids(ids: list):
    """Save list of authorized user IDs."""
    with open(AUTHORIZED_IDS_FILE, 'w') as f:
        json.dump(ids, f, indent=2)


def add_authorized_user(user_id: int):
    """Explicitly authorize a user ID."""
    ids = load_authorized_ids()
    if user_id not in ids:
        ids.append(user_id)
        save_authorized_ids(ids)
        logger.info(f"Manually authorized user ID: {user_id}")



def is_user_allowed(username: str, user_id: int) -> tuple[bool, str]:
    """
    Check if user is allowed to use the bot.
    
    Flow:
    1. If user is OWNER -> allow
    2. If user_id is already authorized -> allow
    3. If username is in whitelist -> authorize this ID and allow
    4. Otherwise -> reject
    
    Returns:
        (is_allowed, message)
    """
    # Check Owner
    if user_id == OWNER_ID:
        return True, "✅ Access granted (Owner)"

    authorized_ids = load_authorized_ids()
    
    # Check if ID is already authorized (instant access)
    if user_id in authorized_ids:
        return True, "✅ Access granted"
    
    # ID not authorized - check if username is in whitelist
    if not username:
        return False, "🚫 You are not allowed to use this service.\n\nContact the owner for access."
    
    username_lower = username.lower()
    allowed_usernames_lower = [u.lower() for u in ALLOWED_USERNAMES]
    
    if username_lower in allowed_usernames_lower:
        # Username is allowed - authorize this ID
        authorized_ids.append(user_id)
        save_authorized_ids(authorized_ids)
        logger.info(f"Authorized new user: @{username} (ID: {user_id})")
        return True, "✅ Access granted"
    
    # Not authorized
    return False, "🚫 You are not allowed to use this service.\n\nContact the owner for access."
