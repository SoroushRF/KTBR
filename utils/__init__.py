"""Utils package initialization."""

from utils.auth import is_user_allowed, load_authorized_ids, save_authorized_ids
from utils.tracking import FaceTrack, FaceTracker, calculate_iou
from utils.queue_manager import (
    is_server_busy,
    get_queue_length,
    get_queue_position,
    is_in_queue,
    add_to_queue,
    remove_from_queue,
    get_next_in_queue,
    estimate_wait_time,
    format_wait_time,
    set_cooldown,
    is_on_cooldown,
    get_cooldown_remaining,
    get_server_status,
)

__all__ = [
    'is_user_allowed',
    'load_authorized_ids', 
    'save_authorized_ids',
    'FaceTrack',
    'FaceTracker',
    'calculate_iou',
    # Queue management
    'is_server_busy',
    'get_queue_length',
    'get_queue_position',
    'is_in_queue',
    'add_to_queue',
    'remove_from_queue',
    'get_next_in_queue',
    'estimate_wait_time',
    'format_wait_time',
    # Cooldown management
    'set_cooldown',
    'is_on_cooldown',
    'get_cooldown_remaining',
    'get_server_status',
]
