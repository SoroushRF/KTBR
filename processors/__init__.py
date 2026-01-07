"""Processors package initialization."""

from processors.face_blur import blur_faces_in_image, blur_faces_in_video, download_model

__all__ = [
    'blur_faces_in_image',
    'blur_faces_in_video',
    'download_model',
]
