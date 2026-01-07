"""
KTBR - Face Tracking Classes
Handles face tracking across video frames.
"""

import cv2


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
