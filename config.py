"""
KTBR Configuration
All configuration settings and constants.
"""

import os
import logging

# =============================================================================
# Load .env file
# =============================================================================
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# =============================================================================
# BOT CONFIGURATION
# =============================================================================

# Bot token from @BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Allowed usernames (comma-separated)
_usernames_str = os.getenv("ALLOWED_USERNAMES", "")
ALLOWED_USERNAMES = [u.strip() for u in _usernames_str.split(",") if u.strip()]

# =============================================================================
# FILE LIMITS
# =============================================================================

MAX_VIDEO_DURATION_SECONDS = 30
MAX_VIDEO_SIZE_MB = 100
MAX_IMAGE_SIZE_MB = 10
MAX_IMAGE_DIMENSION = 1920  # FHD

# =============================================================================
# PATHS
# =============================================================================

# Data file to store authorized user IDs
DATA_DIR = os.getenv("DATA_DIR", ".")
AUTHORIZED_IDS_FILE = os.path.join(DATA_DIR, "authorized_ids.json")

# =============================================================================
# PROCESSING ESTIMATES
# =============================================================================

ESTIMATE_VIDEO_SEC_PER_MB = 2.5
ESTIMATE_IMAGE_SEC_PER_MB = 0.5

# =============================================================================
# FACE DETECTION MODEL
# =============================================================================

YUNET_MODEL = "face_detection_yunet_2023mar.onnx"
YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"

# =============================================================================
# LOGGING
# =============================================================================

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("ktbr")

# =============================================================================
# ACTIVE TASKS (for cancellation)
# =============================================================================

# Stores user_id -> {"temp_dir": path, "cancel_event": threading.Event}
active_tasks: dict = {}
