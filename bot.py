"""
KTBR - Face Blurring Telegram Bot
Whitelist-based access with username->ID locking
"""

import cv2
import numpy as np
import os
import json
import asyncio
import urllib.request
import subprocess
import shutil
import tempfile
import logging
import time
import gc
from datetime import datetime
from typing import Optional

from telegram import Update, Bot, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# =============================================================================
# ACTIVE PROCESSING TASKS (for cancellation)
# =============================================================================
# Stores user_id -> {"task": asyncio.Task, "temp_dir": path, "cancelled": bool}
active_tasks: dict = {}

# =============================================================================
# CONFIGURATION (loaded from environment variables)
# =============================================================================

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, will use environment variables directly

# Your bot token from @BotFather (set via BOT_TOKEN environment variable)
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Allowed usernames (set via ALLOWED_USERNAMES environment variable, comma-separated)
_usernames_str = os.getenv("ALLOWED_USERNAMES", "")
ALLOWED_USERNAMES = [u.strip() for u in _usernames_str.split(",") if u.strip()]

# File limits
MAX_VIDEO_DURATION_SECONDS = 30
MAX_VIDEO_SIZE_MB = 100
MAX_IMAGE_SIZE_MB = 10
MAX_IMAGE_DIMENSION = 1920  # FHD

# Data file to store authorized user IDs
# Use DATA_DIR env var for Docker volume mounting, defaults to current directory
DATA_DIR = os.getenv("DATA_DIR", ".")
AUTHORIZED_IDS_FILE = os.path.join(DATA_DIR, "authorized_ids.json")

# Processing time estimates (seconds per MB)
ESTIMATE_VIDEO_SEC_PER_MB = 2.5  # Approximate processing time
ESTIMATE_IMAGE_SEC_PER_MB = 0.5

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# =============================================================================
# USER AUTHORIZATION
# =============================================================================

def load_authorized_ids() -> list:
    """Load list of authorized user IDs."""
    if os.path.exists(AUTHORIZED_IDS_FILE):
        try:
            with open(AUTHORIZED_IDS_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    return []

def save_authorized_ids(ids: list):
    """Save list of authorized user IDs."""
    with open(AUTHORIZED_IDS_FILE, 'w') as f:
        json.dump(ids, f, indent=2)

def is_user_allowed(username: str, user_id: int) -> tuple[bool, str]:
    """
    Check if user is allowed to use the bot.
    
    Flow:
    1. If user_id is already authorized → allow
    2. If username is in whitelist → authorize this ID and allow
    3. Otherwise → reject
    
    Returns:
        (is_allowed, message)
    """
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

# =============================================================================
# FACE BLURRING LOGIC (from main.py)
# =============================================================================

def download_model(model_name, url):
    """Download face detection model if not present."""
    if not os.path.exists(model_name):
        logger.info(f"Downloading {model_name}...")
        try:
            opener = urllib.request.build_opener()
            opener.addheaders = [('User-agent', 'Mozilla/5.0')]
            urllib.request.install_opener(opener)
            urllib.request.urlretrieve(url, model_name)
            logger.info(f"Downloaded {model_name}")
            return True
        except Exception as e:
            logger.error(f"Error downloading model: {e}")
            return False
    return True

def calculate_iou(box1, box2):
    """Calculate Intersection over Union between two boxes [x, y, w, h]."""
    x1, y1, w1, h1 = box1
    x2, y2, w2, h2 = box2
    
    xa1, ya1, xa2, ya2 = x1, y1, x1 + w1, y1 + h1
    xb1, yb1, xb2, yb2 = x2, y2, x2 + w2, y2 + h2
    
    inter_x1 = max(xa1, xb1)
    inter_y1 = max(ya1, yb1)
    inter_x2 = min(xa2, xb2)
    inter_y2 = min(ya2, yb2)
    
    if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
        return 0.0
    
    inter_area = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
    area1 = w1 * h1
    area2 = w2 * h2
    union_area = area1 + area2 - inter_area
    
    return inter_area / union_area if union_area > 0 else 0.0

class FaceTrack:
    """Represents a single tracked face."""
    _next_id = 0
    
    def __init__(self, bbox, frame):
        self.id = FaceTrack._next_id
        FaceTrack._next_id += 1
        self.bbox = list(bbox)
        self.frames_since_detection = 0
        self.max_frames_without_detection = 20
        self.tracker = None
        self.init_tracker(frame, bbox)
    
    def init_tracker(self, frame, bbox):
        try:
            self.tracker = cv2.TrackerKCF_create()
            x, y, w, h = [int(v) for v in bbox]
            h_frame, w_frame = frame.shape[:2]
            x = max(0, min(x, w_frame - 1))
            y = max(0, min(y, h_frame - 1))
            w = max(1, min(w, w_frame - x))
            h = max(1, min(h, h_frame - y))
            self.tracker.init(frame, (x, y, w, h))
        except Exception as e:
            self.tracker = None
    
    def update_with_detection(self, bbox, frame):
        self.bbox = list(bbox)
        self.frames_since_detection = 0
        self.init_tracker(frame, bbox)
    
    def update_with_tracker(self, frame):
        self.frames_since_detection += 1
        if self.tracker is not None:
            try:
                success, box = self.tracker.update(frame)
                if success:
                    self.bbox = [int(box[0]), int(box[1]), int(box[2]), int(box[3])]
                    return True
            except:
                pass
        return False
    
    def is_valid(self):
        return self.frames_since_detection < self.max_frames_without_detection
    
    def get_blur_bbox(self):
        x, y, w, h = self.bbox
        expand_ratio = 0.6
        expand_w = int(w * expand_ratio / 2)
        expand_h = int(h * expand_ratio / 2)
        return [x - expand_w, y - expand_h, w + expand_w * 2, h + expand_h * 2]

class FaceTracker:
    """Manages multiple face tracks."""
    
    def __init__(self):
        self.tracks = []
        self.iou_threshold = 0.15
        self.distance_threshold_ratio = 1.5
    
    def _get_center(self, bbox):
        x, y, w, h = bbox
        return (x + w / 2, y + h / 2)
    
    def _get_distance(self, bbox1, bbox2):
        c1 = self._get_center(bbox1)
        c2 = self._get_center(bbox2)
        return ((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2) ** 0.5
    
    def update(self, detections, frame):
        for track in self.tracks:
            track.update_with_tracker(frame)
        
        used_detections = set()
        
        for track in self.tracks:
            best_score = -1
            best_det_idx = -1
            
            for i, det in enumerate(detections):
                if i in used_detections:
                    continue
                
                iou = calculate_iou(track.bbox, det)
                if iou >= self.iou_threshold:
                    score = iou + 1
                    if score > best_score:
                        best_score = score
                        best_det_idx = i
                else:
                    avg_size = (track.bbox[2] + track.bbox[3] + det[2] + det[3]) / 4
                    distance = self._get_distance(track.bbox, det)
                    max_distance = avg_size * self.distance_threshold_ratio
                    
                    if distance < max_distance:
                        score = 1 - (distance / max_distance)
                        if score > best_score:
                            best_score = score
                            best_det_idx = i
            
            if best_det_idx >= 0:
                track.update_with_detection(detections[best_det_idx], frame)
                used_detections.add(best_det_idx)
        
        for i, det in enumerate(detections):
            if i not in used_detections:
                self.tracks.append(FaceTrack(det, frame))
        
        self.tracks = [t for t in self.tracks if t.is_valid()]
    
    def get_blur_regions(self):
        return [track.get_blur_bbox() for track in self.tracks]

def apply_elliptical_blur(image, bbox):
    """Apply elliptical blur to a region."""
    h_img, w_img = image.shape[:2]
    x, y, w, h = bbox
    
    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(w_img, x + w)
    y2 = min(h_img, y + h)
    
    new_w = x2 - x1
    new_h = y2 - y1
    
    if new_w <= 0 or new_h <= 0:
        return
    
    roi = image[y1:y2, x1:x2].copy()
    
    kw = (new_w // 3) | 1
    kh = (new_h // 3) | 1
    kw = max(kw, 15)
    kh = max(kh, 15)
    
    try:
        blurred_roi = cv2.GaussianBlur(roi, (kw, kh), 0)
        
        mask = np.zeros((new_h, new_w), dtype=np.uint8)
        center = (new_w // 2, new_h // 2)
        axes = (new_w // 2, new_h // 2)
        cv2.ellipse(mask, center, axes, 0, 0, 360, 255, -1)
        
        mask = cv2.GaussianBlur(mask, (21, 21), 0)
        mask_3ch = cv2.merge([mask, mask, mask]).astype(float) / 255.0
        
        blended = (blurred_roi * mask_3ch + roi * (1 - mask_3ch)).astype(np.uint8)
        image[y1:y2, x1:x2] = blended
    except:
        pass

def blur_faces_in_image(input_path: str, output_path: str) -> bool:
    """Blur faces in an image."""
    yunet_model = "face_detection_yunet_2023mar.onnx"
    yunet_url = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
    
    if not download_model(yunet_model, yunet_url):
        return False
    
    try:
        image = cv2.imread(input_path)
        if image is None:
            return False
        
        height, width = image.shape[:2]
        
        detector = cv2.FaceDetectorYN.create(
            model=yunet_model,
            config="",
            input_size=(width, height),
            score_threshold=0.5,
            nms_threshold=0.3,
            top_k=5000
        )
        
        results = detector.detect(image)
        
        if results[1] is not None:
            for face in results[1]:
                bbox = face[0:4].astype(int).tolist()
                # Expand bbox for blur
                x, y, w, h = bbox
                expand_ratio = 0.6
                expand_w = int(w * expand_ratio / 2)
                expand_h = int(h * expand_ratio / 2)
                blur_bbox = [x - expand_w, y - expand_h, w + expand_w * 2, h + expand_h * 2]
                apply_elliptical_blur(image, blur_bbox)
        
        cv2.imwrite(output_path, image)
        return True
    except Exception as e:
        logger.error(f"Error blurring image: {e}")
        return False

def blur_faces_in_video(input_path: str, output_path: str, edge_crop_percent: int = 2, cancel_check=None) -> tuple[bool, bool]:
    """
    Blur faces in a video with tracking.
    
    Args:
        input_path: Path to input video
        output_path: Path to output video
        edge_crop_percent: Percentage to crop from edges
        cancel_check: Optional callable that returns True if processing should be cancelled
    
    Returns:
        (success, was_cancelled) tuple
    """
    yunet_model = "face_detection_yunet_2023mar.onnx"
    yunet_url = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
    
    if not download_model(yunet_model, yunet_url):
        return False, False
    
    try:
        detector = cv2.FaceDetectorYN.create(
            model=yunet_model,
            config="",
            input_size=(320, 320),
            score_threshold=0.5,
            nms_threshold=0.3,
            top_k=5000
        )
    except Exception as e:
        logger.error(f"Failed to load YuNet: {e}")
        return False, False

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        return False, False

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    crop_x = int(width * edge_crop_percent / 100)
    crop_y = int(height * edge_crop_percent / 100)
    cropped_width = width - (2 * crop_x)
    cropped_height = height - (2 * crop_y)
    
    if cropped_width <= 0 or cropped_height <= 0:
        cap.release()
        return False, False
    
    # Temporary output without audio
    temp_output = output_path + ".temp.mp4"
    
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(temp_output, fourcc, fps, (cropped_width, cropped_height))
    
    face_tracker = FaceTracker()
    FaceTrack._next_id = 0
    
    was_cancelled = False
    frame_count = 0
    
    while True:
        # Check for cancellation every frame
        if cancel_check and cancel_check():
            logger.info("Video processing cancelled by user")
            was_cancelled = True
            break
        
        success, frame = cap.read()
        if not success:
            break
        
        frame_count += 1
        
        detector.setInputSize((width, height))
        results = detector.detect(frame)
        
        detections = []
        if results[1] is not None:
            for face in results[1]:
                detections.append(face[0:4].astype(int).tolist())
        
        face_tracker.update(detections, frame)
        blur_regions = face_tracker.get_blur_regions()
        
        for bbox in blur_regions:
            apply_elliptical_blur(frame, bbox)
        
        cropped_frame = frame[crop_y:height-crop_y, crop_x:width-crop_x]
        out.write(cropped_frame)

    cap.release()
    out.release()
    
    # Force garbage collection and wait for Windows to release file handles
    del out
    del cap
    gc.collect()
    time.sleep(0.5)  # Give Windows time to release file handles
    
    # If cancelled, clean up and return
    if was_cancelled:
        try:
            os.remove(temp_output)
        except:
            pass
        return False, True
    
    # Merge audio using ffmpeg
    ffmpeg_available = shutil.which('ffmpeg') is not None
    
    if ffmpeg_available:
        try:
            # Re-encode with H.264 for Telegram compatibility
            cmd = [
                'ffmpeg', '-y',
                '-i', temp_output,
                '-i', input_path,
                '-c:v', 'libx264',           # H.264 codec for Telegram
                '-preset', 'fast',            # Encoding speed
                '-crf', '23',                 # Quality (lower = better, 18-28 is good)
                '-pix_fmt', 'yuv420p',        # Pixel format for compatibility
                '-c:a', 'aac',
                '-b:a', '128k',
                '-map', '0:v:0',
                '-map', '1:a:0?',
                '-map_metadata', '-1',
                '-map_chapters', '-1',
                '-fflags', '+bitexact',
                '-movflags', '+faststart',    # Enable streaming
                '-shortest',
                output_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                try:
                    os.remove(temp_output)
                except:
                    pass
                return True, False
            else:
                logger.warning(f"FFmpeg failed: {result.stderr}")
                # Fallback: use video without audio
                try:
                    shutil.move(temp_output, output_path)
                except:
                    pass
                return True, False
        except Exception as e:
            logger.error(f"FFmpeg error: {e}")
            if os.path.exists(temp_output):
                try:
                    shutil.move(temp_output, output_path)
                except:
                    pass
            return True, False
    else:
        try:
            shutil.move(temp_output, output_path)
        except:
            pass
        return True, False

# =============================================================================
# TELEGRAM BOT HANDLERS
# =============================================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user = update.effective_user
    username = user.username
    user_id = user.id
    
    is_allowed, message = is_user_allowed(username, user_id)
    
    if not is_allowed:
        await update.message.reply_text(message)
        return
    
    welcome_message = f"""
👋 Welcome, @{username}!

🔒 **KTBR - Face Blur Bot**

I can blur faces in your videos and images.

📤 **Just send me a file:**

📹 **Video:**
• Max duration: {MAX_VIDEO_DURATION_SECONDS} seconds
• Max size: {MAX_VIDEO_SIZE_MB} MB

🖼️ **Image:**
• Max resolution: Full HD ({MAX_IMAGE_DIMENSION}px)  
• Max size: {MAX_IMAGE_SIZE_MB} MB

📋 **Commands:**
/start - Show this welcome message
/upload - How to upload files
/stop - Cancel current processing

Simply upload a video or image and I'll process it for you!
"""
    await update.message.reply_text(welcome_message, parse_mode='Markdown')


async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /upload command - explains how to upload."""
    user = update.effective_user
    is_allowed, message = is_user_allowed(user.username, user.id)
    
    if not is_allowed:
        await update.message.reply_text(message)
        return
    
    upload_message = f"""
📤 **How to Upload Files**

**Option 1: Direct Send**
Just drag & drop or attach a video/image directly in this chat!

**Option 2: Forward**
Forward a video or image from another chat.

**Option 3: File Upload**
Click 📎 and select your file.

━━━━━━━━━━━━━━━━━━━━━

📹 **Video Limits:**
• Max duration: {MAX_VIDEO_DURATION_SECONDS} seconds
• Max size: {MAX_VIDEO_SIZE_MB} MB
• Formats: MP4, AVI, MOV, etc.

🖼️ **Image Limits:**
• Max resolution: {MAX_IMAGE_DIMENSION}x{MAX_IMAGE_DIMENSION}
• Max size: {MAX_IMAGE_SIZE_MB} MB
• Formats: JPG, PNG, etc.

━━━━━━━━━━━━━━━━━━━━━

⏳ Processing time depends on file size.
Use /stop to cancel if needed.
"""
    await update.message.reply_text(upload_message, parse_mode='Markdown')


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stop command - cancels current processing."""
    user = update.effective_user
    user_id = user.id
    
    is_allowed, message = is_user_allowed(user.username, user_id)
    if not is_allowed:
        await update.message.reply_text(message)
        return
    
    # Check if user has an active task
    if user_id not in active_tasks:
        await update.message.reply_text(
            "ℹ️ No active processing to stop.\n\n"
            "Send a video or image to start processing."
        )
        return
    
    task_info = active_tasks[user_id]
    task_info["cancelled"] = True
    
    # Clean up temp directory if it exists
    temp_dir = task_info.get("temp_dir")
    if temp_dir and os.path.exists(temp_dir):
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info(f"Cleaned up temp dir for user {user_id}: {temp_dir}")
        except Exception as e:
            logger.error(f"Error cleaning temp dir: {e}")
    
    # Remove from active tasks
    del active_tasks[user_id]
    
    await update.message.reply_text(
        "🛑 **Processing stopped!**\n\n"
        "All temporary files have been deleted.\n\n"
        "📤 Send another file when you're ready.",
        parse_mode='Markdown'
    )
    logger.info(f"User {user_id} cancelled processing")

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
    estimated_time = max(estimated_time, 5)  # Minimum 5 seconds
    
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
    try:
        temp_dir = tempfile.mkdtemp()
        
        # Register active task
        active_tasks[user_id] = {
            "temp_dir": temp_dir,
            "cancelled": False,
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
        if user_id in active_tasks and active_tasks[user_id].get("cancelled"):
            await update.message.reply_text(
                "🛑 **Processing aborted!**\n\n"
                "All files have been cleaned up.",
                parse_mode='Markdown'
            )
            return
        
        # Create cancel check function
        def check_cancelled():
            return user_id in active_tasks and active_tasks[user_id].get("cancelled", False)
        
        # Process video in background thread (allows /stop to be received)
        success, was_cancelled = await asyncio.to_thread(
            blur_faces_in_video, input_path, output_path, 2, check_cancelled
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
            # Read file into memory to avoid file locking issues
            with open(output_path, 'rb') as f:
                video_data = f.read()
            
            # Send from memory
            from io import BytesIO
            await update.message.reply_document(
                document=BytesIO(video_data),
                filename=f"blurred_{os.path.splitext(file_name)[0]}.mp4",
                caption="✅ **Done!** Here's your processed video with blurred faces."
            )
            # Prompt for next file
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
        # Remove from active tasks
        if user_id in active_tasks:
            del active_tasks[user_id]
        
        # Clean up temp directory
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except:
                pass


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo uploads."""
    user = update.effective_user
    username = user.username
    user_id = user.id
    
    is_allowed, message = is_user_allowed(username, user_id)
    if not is_allowed:
        await update.message.reply_text(message)
        return
    
    # Get the largest photo
    photo = update.message.photo[-1] if update.message.photo else None
    
    if not photo:
        await update.message.reply_text("❌ No photo detected. Please send a valid image.")
        return
    
    # Check dimensions
    if photo.width > MAX_IMAGE_DIMENSION or photo.height > MAX_IMAGE_DIMENSION:
        await update.message.reply_text(
            f"❌ Image resolution too high!\n\n"
            f"Your image: {photo.width}x{photo.height}\n"
            f"Maximum: {MAX_IMAGE_DIMENSION}x{MAX_IMAGE_DIMENSION}"
        )
        return
    
    # Check file size
    file_size_mb = photo.file_size / (1024 * 1024)
    
    if file_size_mb > MAX_IMAGE_SIZE_MB:
        await update.message.reply_text(
            f"❌ Image too large!\n\n"
            f"Your file: {file_size_mb:.1f} MB\n"
            f"Maximum: {MAX_IMAGE_SIZE_MB} MB"
        )
        return
    
    # Estimate processing time
    estimated_time = max(int(file_size_mb * ESTIMATE_IMAGE_SEC_PER_MB), 2)
    
    await update.message.reply_text(
        f"⏳ **Processing your image...**\n\n"
        f"📐 Resolution: {photo.width}x{photo.height}\n"
        f"⏱️ Estimated time: ~{estimated_time} seconds\n\n"
        f"Please wait...",
        parse_mode='Markdown'
    )
    
    # Download and process
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = os.path.join(temp_dir, "input.jpg")
            output_path = os.path.join(temp_dir, "output.jpg")
            
            # Download file
            file = await context.bot.get_file(photo.file_id)
            await file.download_to_drive(input_path)
            
            # Process image in background thread
            success = await asyncio.to_thread(blur_faces_in_image, input_path, output_path)
            
            if success and os.path.exists(output_path):
                with open(output_path, 'rb') as f:
                    image_data = f.read()
                
                from io import BytesIO
                await update.message.reply_document(
                    document=BytesIO(image_data),
                    filename="blurred_image.jpg",
                    caption="✅ **Done!** Here's your processed image with blurred faces."
                )
                # Prompt for next file
                await update.message.reply_text(
                    "📤 Send another **video** or **image** to blur faces.",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text("❌ Failed to process image. Please try again.\n\n📤 Send another file to try again.")
    
    except Exception as e:
        logger.error(f"Error processing photo: {e}")
        await update.message.reply_text(f"❌ An error occurred: {str(e)}")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle document uploads (for images/videos sent as files)."""
    document = update.message.document
    
    if not document or not document.mime_type:
        await update.message.reply_text("❌ Unsupported file type.")
        return
    
    mime_type = document.mime_type.lower()
    
    if mime_type.startswith('video/'):
        await handle_video(update, context)
    elif mime_type.startswith('image/'):
        # For images sent as documents, we need different handling
        user = update.effective_user
        is_allowed, message = is_user_allowed(user.username, user.id)
        if not is_allowed:
            await update.message.reply_text(message)
            return
        
        file_size_mb = document.file_size / (1024 * 1024)
        
        if file_size_mb > MAX_IMAGE_SIZE_MB:
            await update.message.reply_text(
                f"❌ Image too large!\n\n"
                f"Your file: {file_size_mb:.1f} MB\n"
                f"Maximum: {MAX_IMAGE_SIZE_MB} MB"
            )
            return
        
        estimated_time = max(int(file_size_mb * ESTIMATE_IMAGE_SEC_PER_MB), 2)
        
        await update.message.reply_text(
            f"⏳ **Processing your image...**\n\n"
            f"📊 File size: {file_size_mb:.1f} MB\n"
            f"⏱️ Estimated time: ~{estimated_time} seconds\n\n"
            f"Please wait...",
            parse_mode='Markdown'
        )
        
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                ext = os.path.splitext(document.file_name)[1] if document.file_name else ".jpg"
                input_path = os.path.join(temp_dir, f"input{ext}")
                output_path = os.path.join(temp_dir, f"output{ext}")
                
                file = await context.bot.get_file(document.file_id)
                await file.download_to_drive(input_path)
                
                success = await asyncio.to_thread(blur_faces_in_image, input_path, output_path)
                
                if success and os.path.exists(output_path):
                    await update.message.reply_document(
                        document=open(output_path, 'rb'),
                        filename=f"blurred_{document.file_name or 'image.jpg'}",
                        caption="✅ **Done!** Here's your processed image with blurred faces."
                    )
                else:
                    await update.message.reply_text("❌ Failed to process image. Please try again.")
        except Exception as e:
            logger.error(f"Error processing document: {e}")
            await update.message.reply_text(f"❌ An error occurred: {str(e)}")
    else:
        await update.message.reply_text(
            "❌ Unsupported file type.\n\n"
            "Please send a video (.mp4, .avi, .mov) or image (.jpg, .png)."
        )

async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle unknown messages."""
    user = update.effective_user
    is_allowed, message = is_user_allowed(user.username, user.id)
    
    if not is_allowed:
        await update.message.reply_text(message)
        return
    
    await update.message.reply_text(
        "📤 Please send me a **video** or **image** to blur faces.\n\n"
        "Use /start to see the file limits.",
        parse_mode='Markdown'
    )

# =============================================================================
# MAIN
# =============================================================================

async def post_init(application: Application):
    """Set up bot commands after initialization."""
    commands = [
        BotCommand("start", "Show welcome message and info"),
        BotCommand("upload", "How to upload files"),
        BotCommand("stop", "Cancel current processing"),
    ]
    await application.bot.set_my_commands(commands)
    logger.info("Bot commands registered with Telegram")

def main():
    """Start the bot."""
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("=" * 60)
        print("ERROR: Please set your bot token!")
        print("=" * 60)
        print("\n1. Go to @BotFather on Telegram")
        print("2. Create a new bot with /newbot")
        print("3. Copy the token and paste it in bot.py")
        print("\n   BOT_TOKEN = 'your_token_here'")
        print("=" * 60)
        return
    
    print("=" * 60)
    print("KTBR - Face Blur Telegram Bot")
    print("=" * 60)
    print(f"Allowed usernames: {ALLOWED_USERNAMES}")
    print("=" * 60)
    
    # Build application with post_init callback
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("upload", upload_command))
    application.add_handler(CommandHandler("stop", stop_command))
    
    # Add message handlers
    application.add_handler(MessageHandler(filters.VIDEO, handle_video))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unknown))
    
    # Start polling
    print("Bot is running... Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

