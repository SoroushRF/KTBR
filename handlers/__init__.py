"""Handlers package initialization."""

from handlers.commands import start_command, upload_command, stop_command, clear_command
from handlers.video import handle_video
from handlers.photo import handle_photo, handle_document, handle_unknown

__all__ = [
    'start_command',
    'upload_command',
    'stop_command',
    'clear_command',
    'handle_video',
    'handle_photo',
    'handle_document',
    'handle_unknown',
]
