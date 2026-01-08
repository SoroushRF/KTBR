"""
KTBR - Voice Anonymization Processor
Anonymizes voice in videos using pitch/formant shifting.
"""

import os
import subprocess
import tempfile
import random

from config import logger


def anonymize_voice_fast(input_video_path: str, output_video_path: str, cancel_check=None) -> tuple[bool, bool]:
    """
    Anonymize voice in video using traditional methods (Fast mode).
    
    Uses FFmpeg's audio filters for:
    - Pitch shifting (±3-6 semitones)
    - Tempo adjustment
    - Subtle distortion
    
    Args:
        input_video_path: Path to input video
        output_video_path: Path to save output video
        cancel_check: Optional callable to check if processing should be cancelled
        
    Returns:
        (success, was_cancelled) tuple
    """
    try:
        if cancel_check and cancel_check():
            return False, True
            
        # Random pitch shift between -6 and +6 semitones (avoiding 0)
        # Positive = higher pitch, Negative = lower pitch
        semitones = random.choice([-6, -5, -4, -3, 3, 4, 5, 6])
        
        # Convert semitones to pitch multiplier
        # Formula: 2^(semitones/12)
        pitch_factor = 2 ** (semitones / 12)
        
        # Tempo adjustment to compensate for pitch change (keeps speech speed natural)
        # When pitch goes up, we slow down; when pitch goes down, we speed up
        tempo_factor = 1 / pitch_factor
        
        # Random subtle variations
        # Add slight additional tempo variation (±5%)
        tempo_variation = random.uniform(0.95, 1.05)
        final_tempo = tempo_factor * tempo_variation
        
        # Clamp tempo to reasonable range
        final_tempo = max(0.5, min(2.0, final_tempo))
        
        logger.info(f"Voice anonymization: pitch={semitones} semitones, tempo={final_tempo:.3f}")
        
        if cancel_check and cancel_check():
            return False, True
        
        # Build FFmpeg command
        # Using asetrate + aresample for pitch shift, then atempo for speed correction
        # asetrate changes pitch by changing sample rate interpretation
        # aresample converts back to original sample rate
        # atempo adjusts speed without changing pitch
        
        # Alternative approach using rubberband filter (if available) or asetrate
        # We'll use the asetrate method as it's built into FFmpeg
        
        audio_filter = (
            f"asetrate=44100*{pitch_factor:.4f},"
            f"aresample=44100,"
            f"atempo={final_tempo:.4f}"
        )
        
        # If tempo is outside atempo's range (0.5-2.0), chain multiple atempo filters
        if final_tempo < 0.5:
            # Chain atempo filters for very slow
            audio_filter = (
                f"asetrate=44100*{pitch_factor:.4f},"
                f"aresample=44100,"
                f"atempo=0.5,atempo={final_tempo/0.5:.4f}"
            )
        elif final_tempo > 2.0:
            # Chain atempo filters for very fast
            audio_filter = (
                f"asetrate=44100*{pitch_factor:.4f},"
                f"aresample=44100,"
                f"atempo=2.0,atempo={final_tempo/2.0:.4f}"
            )
        
        cmd = [
            'ffmpeg',
            '-y',  # Overwrite output
            '-i', input_video_path,
            '-af', audio_filter,
            '-c:v', 'copy',  # Copy video stream (no re-encoding)
            '-c:a', 'aac',   # Re-encode audio to AAC
            '-b:a', '128k',  # Audio bitrate
            '-map_metadata', '-1',  # Strip metadata
            output_video_path
        ]
        
        logger.info(f"Running FFmpeg: {' '.join(cmd)}")
        
        # Run FFmpeg
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        
        if cancel_check and cancel_check():
            # Clean up output if cancelled
            if os.path.exists(output_video_path):
                os.remove(output_video_path)
            return False, True
        
        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr}")
            return False, False
        
        if not os.path.exists(output_video_path):
            logger.error("Output file was not created")
            return False, False
        
        logger.info("Voice anonymization (Fast) completed successfully")
        return True, False
        
    except subprocess.TimeoutExpired:
        logger.error("FFmpeg timeout")
        return False, False
    except Exception as e:
        logger.error(f"Voice anonymization error: {e}")
        return False, False


def anonymize_voice_secure(input_video_path: str, output_video_path: str, cancel_check=None) -> tuple[bool, bool]:
    """
    Anonymize voice using AI voice conversion (Secure mode).
    
    This is a placeholder - will be implemented in Phase 4.
    For now, falls back to Fast mode with stronger settings.
    
    Args:
        input_video_path: Path to input video
        output_video_path: Path to save output video
        cancel_check: Optional callable to check if processing should be cancelled
        
    Returns:
        (success, was_cancelled) tuple
    """
    # TODO: Implement AI voice conversion using FreeVC
    # For now, use Fast mode with more aggressive settings
    logger.info("Secure mode not yet implemented, using enhanced Fast mode")
    
    try:
        if cancel_check and cancel_check():
            return False, True
        
        # More aggressive pitch shift for "secure" mode
        semitones = random.choice([-8, -7, 7, 8])
        pitch_factor = 2 ** (semitones / 12)
        tempo_factor = 1 / pitch_factor
        tempo_variation = random.uniform(0.90, 1.10)  # More variation
        final_tempo = max(0.5, min(2.0, tempo_factor * tempo_variation))
        
        # Add some audio effects for extra anonymization
        # - highpass: remove very low frequencies
        # - lowpass: remove very high frequencies  
        # - chorus: adds slight doubling effect
        audio_filter = (
            f"asetrate=44100*{pitch_factor:.4f},"
            f"aresample=44100,"
            f"atempo={final_tempo:.4f},"
            f"highpass=f=100,"
            f"lowpass=f=8000"
        )
        
        cmd = [
            'ffmpeg',
            '-y',
            '-i', input_video_path,
            '-af', audio_filter,
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-map_metadata', '-1',
            output_video_path
        ]
        
        logger.info(f"Running FFmpeg (Secure): {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if cancel_check and cancel_check():
            if os.path.exists(output_video_path):
                os.remove(output_video_path)
            return False, True
        
        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr}")
            return False, False
        
        if not os.path.exists(output_video_path):
            logger.error("Output file was not created")
            return False, False
        
        logger.info("Voice anonymization (Secure placeholder) completed")
        return True, False
        
    except Exception as e:
        logger.error(f"Secure voice anonymization error: {e}")
        return False, False
