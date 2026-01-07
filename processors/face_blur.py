"""
KTBR - Face Blur Processor
Handles face detection and blurring for images and videos.
"""

import cv2
import numpy as np
import os
import urllib.request
import subprocess
import shutil
import gc
import time

from config import YUNET_MODEL, YUNET_URL, logger
from utils.tracking import FaceTrack, FaceTracker


def download_model(model_name: str = YUNET_MODEL, url: str = YUNET_URL) -> bool:
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
    if not download_model():
        return False
    
    try:
        image = cv2.imread(input_path)
        if image is None:
            return False
        
        height, width = image.shape[:2]
        
        detector = cv2.FaceDetectorYN.create(
            model=YUNET_MODEL,
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
    if not download_model():
        return False, False
    
    try:
        detector = cv2.FaceDetectorYN.create(
            model=YUNET_MODEL,
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
    
    temp_output = output_path + ".temp.mp4"
    
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(temp_output, fourcc, fps, (cropped_width, cropped_height))
    
    face_tracker = FaceTracker()
    FaceTrack._next_id = 0
    
    was_cancelled = False
    frame_count = 0
    
    while True:
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
    
    del out
    del cap
    gc.collect()
    time.sleep(0.5)
    
    if was_cancelled:
        try:
            os.remove(temp_output)
        except:
            pass
        return False, True
    
    ffmpeg_available = shutil.which('ffmpeg') is not None
    
    if ffmpeg_available:
        try:
            cmd = [
                'ffmpeg', '-y',
                '-i', temp_output,
                '-i', input_path,
                '-c:v', 'libx264',
                '-preset', 'fast',
                '-crf', '23',
                '-pix_fmt', 'yuv420p',
                '-c:a', 'aac',
                '-b:a', '128k',
                '-map', '0:v:0',
                '-map', '1:a:0?',
                '-map_metadata', '-1',
                '-map_chapters', '-1',
                '-fflags', '+bitexact',
                '-movflags', '+faststart',
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
