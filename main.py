import cv2
import numpy as np
import os
import glob
import urllib.request
import subprocess
import shutil

def find_video_files():
    """Finds video files in the current directory."""
    extensions = ['*.mp4', '*.avi', '*.mov', '*.mkv', '*.flv', '*.wmv']
    video_files = []
    for ext in extensions:
        video_files.extend(glob.glob(ext))
        video_files.extend(glob.glob(ext.upper()))
    
    unique_files = set(video_files)
    filtered_files = [f for f in unique_files if '_blurred' not in f and '_result' not in f and not f.startswith('temp_')]
    return list(filtered_files)

def download_model(model_name, url):
    if not os.path.exists(model_name):
        print(f"Downloading {model_name}...")
        try:
            opener = urllib.request.build_opener()
            opener.addheaders = [('User-agent', 'Mozilla/5.0')]
            urllib.request.install_opener(opener)
            urllib.request.urlretrieve(url, model_name)
            print(f"Downloaded {model_name}")
            return True
        except Exception as e:
            print(f"Error downloading model: {e}")
            return False
    return True

def calculate_iou(box1, box2):
    """Calculate Intersection over Union between two boxes [x, y, w, h]."""
    x1, y1, w1, h1 = box1
    x2, y2, w2, h2 = box2
    
    # Convert to corners
    xa1, ya1, xa2, ya2 = x1, y1, x1 + w1, y1 + h1
    xb1, yb1, xb2, yb2 = x2, y2, x2 + w2, y2 + h2
    
    # Intersection
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
        self.bbox = list(bbox)  # [x, y, w, h]
        self.frames_since_detection = 0
        self.max_frames_without_detection = 20  # Keep tracking for 20 frames after losing detection
        self.tracker = None
        self.init_tracker(frame, bbox)
    
    def init_tracker(self, frame, bbox):
        """Initialize OpenCV tracker."""
        try:
            # Use CSRT for accuracy or KCF for speed
            self.tracker = cv2.TrackerKCF_create()
            x, y, w, h = [int(v) for v in bbox]
            # Ensure bbox is valid
            h_frame, w_frame = frame.shape[:2]
            x = max(0, min(x, w_frame - 1))
            y = max(0, min(y, h_frame - 1))
            w = max(1, min(w, w_frame - x))
            h = max(1, min(h, h_frame - y))
            self.tracker.init(frame, (x, y, w, h))
        except Exception as e:
            self.tracker = None
    
    def update_with_detection(self, bbox, frame):
        """Update track with a new detection."""
        self.bbox = list(bbox)
        self.frames_since_detection = 0
        # Re-initialize tracker with new detection
        self.init_tracker(frame, bbox)
    
    def update_with_tracker(self, frame):
        """Update track using the tracker (no detection available)."""
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
        """Check if track is still valid."""
        return self.frames_since_detection < self.max_frames_without_detection
    
    def get_blur_bbox(self):
        """Get expanded bbox for blurring."""
        x, y, w, h = self.bbox
        expand_ratio = 0.6  # 60% larger than detected face
        expand_w = int(w * expand_ratio / 2)
        expand_h = int(h * expand_ratio / 2)
        return [x - expand_w, y - expand_h, w + expand_w * 2, h + expand_h * 2]

class FaceTracker:
    """Manages multiple face tracks."""
    
    def __init__(self):
        self.tracks = []
        self.iou_threshold = 0.15  # Lower threshold for fast-moving faces
        self.distance_threshold_ratio = 1.5  # Max distance as ratio of face size
    
    def _get_center(self, bbox):
        """Get center point of a bounding box."""
        x, y, w, h = bbox
        return (x + w / 2, y + h / 2)
    
    def _get_distance(self, bbox1, bbox2):
        """Get distance between centers of two bounding boxes."""
        c1 = self._get_center(bbox1)
        c2 = self._get_center(bbox2)
        return ((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2) ** 0.5
    
    def update(self, detections, frame):
        """Update tracks with new detections."""
        # First, try to update existing tracks with tracker
        for track in self.tracks:
            track.update_with_tracker(frame)
        
        # Match detections to existing tracks using IoU + distance fallback
        used_detections = set()
        
        for track in self.tracks:
            best_score = -1
            best_det_idx = -1
            
            for i, det in enumerate(detections):
                if i in used_detections:
                    continue
                
                # Try IoU first
                iou = calculate_iou(track.bbox, det)
                if iou >= self.iou_threshold:
                    score = iou + 1  # IoU match gets bonus
                    if score > best_score:
                        best_score = score
                        best_det_idx = i
                else:
                    # Fallback: distance-based matching
                    # If centers are close relative to face size, consider it a match
                    avg_size = (track.bbox[2] + track.bbox[3] + det[2] + det[3]) / 4
                    distance = self._get_distance(track.bbox, det)
                    max_distance = avg_size * self.distance_threshold_ratio
                    
                    if distance < max_distance:
                        # Score based on how close (closer = higher score)
                        score = 1 - (distance / max_distance)
                        if score > best_score:
                            best_score = score
                            best_det_idx = i
            
            if best_det_idx >= 0:
                # Update track with matched detection
                track.update_with_detection(detections[best_det_idx], frame)
                used_detections.add(best_det_idx)
        
        # Create new tracks for unmatched detections
        for i, det in enumerate(detections):
            if i not in used_detections:
                self.tracks.append(FaceTrack(det, frame))
        
        # Remove invalid tracks
        self.tracks = [t for t in self.tracks if t.is_valid()]
    
    def get_blur_regions(self):
        """Get all regions to blur."""
        return [track.get_blur_bbox() for track in self.tracks]

def apply_elliptical_blur(image, bbox):
    """Apply elliptical blur to a region."""
    h_img, w_img = image.shape[:2]
    x, y, w, h = bbox
    
    # Clamp to image bounds
    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(w_img, x + w)
    y2 = min(h_img, y + h)
    
    new_w = x2 - x1
    new_h = y2 - y1
    
    if new_w <= 0 or new_h <= 0:
        return
    
    roi = image[y1:y2, x1:x2].copy()
    
    # Strong blur
    kw = (new_w // 3) | 1
    kh = (new_h // 3) | 1
    kw = max(kw, 15)
    kh = max(kh, 15)
    
    try:
        blurred_roi = cv2.GaussianBlur(roi, (kw, kh), 0)
        
        # Elliptical mask
        mask = np.zeros((new_h, new_w), dtype=np.uint8)
        center = (new_w // 2, new_h // 2)
        axes = (new_w // 2, new_h // 2)
        cv2.ellipse(mask, center, axes, 0, 0, 360, 255, -1)
        
        # Feather edges
        mask = cv2.GaussianBlur(mask, (21, 21), 0)
        mask_3ch = cv2.merge([mask, mask, mask]).astype(float) / 255.0
        
        # Blend
        blended = (blurred_roi * mask_3ch + roi * (1 - mask_3ch)).astype(np.uint8)
        image[y1:y2, x1:x2] = blended
    except:
        pass

def blur_faces_in_video(video_path, edge_crop_percent=2):
    """
    Process video to blur faces with hybrid tracking.
    
    Args:
        video_path: Path to input video
        edge_crop_percent: Percentage to crop from each edge (default 2% from each side)
    """
    print(f"Processing: {video_path}")
    
    # Download YuNet model
    yunet_model = "face_detection_yunet_2023mar.onnx"
    yunet_url = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
    
    if not download_model(yunet_model, yunet_url):
        print("Failed to get face detection model.")
        return
    
    try:
        detector = cv2.FaceDetectorYN.create(
            model=yunet_model,
            config="",
            input_size=(320, 320),
            score_threshold=0.5,
            nms_threshold=0.3,
            top_k=5000
        )
        print("Using YuNet Face Detector with Hybrid Tracking.")
    except Exception as e:
        print(f"Failed to load YuNet: {e}")
        return

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Failed to open video: {video_path}")
        return

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    # Calculate crop in pixels based on percentage
    crop_x = int(width * edge_crop_percent / 100)   # Pixels to crop from left and right
    crop_y = int(height * edge_crop_percent / 100)  # Pixels to crop from top and bottom
    
    # Calculate cropped dimensions
    cropped_width = width - (2 * crop_x)
    cropped_height = height - (2 * crop_y)
    
    print(f"Edge crop: {edge_crop_percent}% from each side ({crop_x}px horizontal, {crop_y}px vertical)")
    
    if cropped_width <= 0 or cropped_height <= 0:
        print(f"Error: Edge crop is too large for video dimensions ({width}x{height})")
        return
    
    print(f"Original: {width}x{height} → Cropped output: {cropped_width}x{cropped_height}")
    
    name, ext = os.path.splitext(video_path)
    output_filename = f"{name}_blurred{ext}"
    
    # Delete existing output file if it exists
    if os.path.exists(output_filename):
        try:
            os.remove(output_filename)
            print(f"Removed existing file: {output_filename}")
        except Exception as e:
            print(f"Warning: Could not remove existing file: {e}")
    
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_filename, fourcc, fps, (cropped_width, cropped_height))
    
    # Initialize tracker
    face_tracker = FaceTracker()
    frame_count = 0
    
    while True:
        success, frame = cap.read()
        if not success:
            break
        
        frame_count += 1
        if frame_count % 50 == 0:
            print(f"Processing frame {frame_count}/{total_frames}... (tracking {len(face_tracker.tracks)} faces)")

        # Detect faces on FULL frame (before crop)
        detector.setInputSize((width, height))
        results = detector.detect(frame)
        
        detections = []
        if results[1] is not None:
            for face in results[1]:
                detections.append(face[0:4].astype(int).tolist())
        
        # Update tracker with detections
        face_tracker.update(detections, frame)
        
        # Get all blur regions (from both detection and tracking)
        blur_regions = face_tracker.get_blur_regions()
        
        # Apply blur on full frame
        for bbox in blur_regions:
            apply_elliptical_blur(frame, bbox)
        
        # Crop the frame (remove crop_x from left/right, crop_y from top/bottom)
        cropped_frame = frame[crop_y:height-crop_y, crop_x:width-crop_x]
        
        out.write(cropped_frame)

    cap.release()
    out.release()
    
    # Now merge audio from original video using ffmpeg
    print("Merging audio from original video...")
    
    # Check if ffmpeg is available
    ffmpeg_available = shutil.which('ffmpeg') is not None
    
    if ffmpeg_available:
        # Rename the processed video to temp
        temp_video = f"{name}_temp_noaudio{ext}"
        try:
            os.rename(output_filename, temp_video)
            
            # Use ffmpeg to combine processed video with original audio
            # -i temp_video: input processed video (no audio)
            # -i video_path: input original video (for audio)
            # -c:v copy: copy video stream without re-encoding
            # -c:a aac: encode audio as AAC (widely compatible)
            # -map 0:v:0: use video from first input
            # -map 1:a:0?: use audio from second input (? means optional, won't fail if no audio)
            # -shortest: end when shortest stream ends
            # -map_metadata -1: strip ALL metadata
            # -fflags +bitexact: remove encoder signatures
            # -flags:v +bitexact: remove video encoder fingerprints
            # -flags:a +bitexact: remove audio encoder fingerprints
            # -map_chapters -1: remove chapter metadata
            # Output as MP4 for maximum compatibility
            
            output_clean = f"{name}_blurred.mp4"
            
            # Delete if exists
            if os.path.exists(output_clean):
                os.remove(output_clean)
            
            cmd = [
                'ffmpeg', '-y',
                '-i', temp_video,
                '-i', video_path,
                '-c:v', 'copy',
                '-c:a', 'aac',
                '-map', '0:v:0',
                '-map', '1:a:0?',
                '-map_metadata', '-1',           # Strip all metadata
                '-map_chapters', '-1',           # Strip chapter metadata
                '-fflags', '+bitexact',          # Remove encoder signatures
                '-flags:v', '+bitexact',         # Remove video fingerprints
                '-flags:a', '+bitexact',         # Remove audio fingerprints
                '-movflags', '+faststart',       # Optimize for streaming
                '-shortest',
                output_clean
            ]
            
            output_filename = output_clean  # Update for cleanup logic
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                # Clean up temp file
                os.remove(temp_video)
                print(f"Saved to {output_filename} (with audio)")
            else:
                print(f"FFmpeg error: {result.stderr}")
                # Restore the video without audio
                os.rename(temp_video, output_filename)
                print(f"Saved to {output_filename} (without audio - ffmpeg failed)")
                
        except Exception as e:
            print(f"Error during audio merge: {e}")
            # Try to recover
            if os.path.exists(temp_video) and not os.path.exists(output_filename):
                os.rename(temp_video, output_filename)
            print(f"Saved to {output_filename} (without audio)")
    else:
        print("FFmpeg not found. Install ffmpeg to preserve audio.")
        print(f"Saved to {output_filename} (without audio)")
    
    print(f"Tracked {FaceTrack._next_id} unique faces throughout the video.")

def main():
    videos = find_video_files()
    if not videos:
        print("No videos found.")
        return
    
    print(f"Found videos: {videos}")
    for video in videos:
        blur_faces_in_video(video)
        # Reset track ID counter for next video
        FaceTrack._next_id = 0

if __name__ == "__main__":
    main()
