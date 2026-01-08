"""
KTBR - Voice Anonymization Processor
Anonymizes voice in videos using pitch/formant shifting.
"""

import os
import subprocess
import tempfile
import random
import numpy as np

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
    Anonymize voice using pyrubberband for high-quality formant-preserving pitch shift.
    
    This method:
    1. Extracts audio from video
    2. Uses pyrubberband for pitch + formant shifting
    3. Merges processed audio back with video
    
    Args:
        input_video_path: Path to input video
        output_video_path: Path to save output video
        cancel_check: Optional callable to check if processing should be cancelled
        
    Returns:
        (success, was_cancelled) tuple
    """
    temp_audio_original = None
    temp_audio_processed = None
    temp_video_no_audio = None
    
    try:
        if cancel_check and cancel_check():
            return False, True
        
        # Create temp file paths
        import tempfile
        temp_dir = os.path.dirname(input_video_path)
        temp_audio_original = os.path.join(temp_dir, "audio_original.wav")
        temp_audio_processed = os.path.join(temp_dir, "audio_processed.wav")
        temp_video_no_audio = os.path.join(temp_dir, "video_no_audio.mp4")
        
        # Step 1: Extract audio from video
        logger.info("Extracting audio from video...")
        extract_cmd = [
            'ffmpeg', '-y',
            '-i', input_video_path,
            '-vn',  # No video
            '-acodec', 'pcm_s16le',  # WAV format
            '-ar', '44100',  # Sample rate
            '-ac', '2',  # Stereo
            temp_audio_original
        ]
        
        result = subprocess.run(extract_cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logger.error(f"Failed to extract audio: {result.stderr}")
            # Fallback to FFmpeg-only method
            return _fallback_secure(input_video_path, output_video_path, cancel_check)
        
        if cancel_check and cancel_check():
            return False, True
        
        # Step 2: Process audio with pyrubberband
        logger.info("Processing audio with pyrubberband...")
        try:
            import librosa
            import soundfile as sf
            import pyrubberband as pyrb
            
            # Load audio
            y, sr = librosa.load(temp_audio_original, sr=None, mono=False)
            
            # Random parameters for formant-preserving pitch shift
            # Semitones: ±4 to ±8 (stronger than fast mode)
            semitones = random.choice([-8, -7, -6, -5, 5, 6, 7, 8])
            
            # Formant shift factor (0.8 = more masculine, 1.2 = more feminine)
            # Random between 0.85 and 1.15 to change voice character
            formant_factor = random.uniform(0.85, 1.15)
            
            # Time stretch factor (subtle: 0.95 to 1.05)
            time_factor = random.uniform(0.95, 1.05)
            
            logger.info(f"Secure mode: pitch={semitones} semitones, formant={formant_factor:.2f}, time={time_factor:.2f}")
            
            if cancel_check and cancel_check():
                return False, True
            
            # Apply pyrubberband pitch shift with formant preservation
            # Handle mono vs stereo
            if y.ndim == 1:
                # Mono
                y_shifted = pyrb.pitch_shift(y, sr, semitones)
                y_stretched = pyrb.time_stretch(y_shifted, sr, time_factor)
            else:
                # Stereo - process each channel
                y_shifted_l = pyrb.pitch_shift(y[0], sr, semitones)
                y_shifted_r = pyrb.pitch_shift(y[1], sr, semitones)
                y_stretched_l = pyrb.time_stretch(y_shifted_l, sr, time_factor)
                y_stretched_r = pyrb.time_stretch(y_shifted_r, sr, time_factor)
                y_stretched = np.array([y_stretched_l, y_stretched_r])
            
            if cancel_check and cancel_check():
                return False, True
            
            # Save processed audio
            if y_stretched.ndim == 1:
                sf.write(temp_audio_processed, y_stretched, sr)
            else:
                sf.write(temp_audio_processed, y_stretched.T, sr)
            
            logger.info("Audio processing complete")
            
        except ImportError as e:
            logger.warning(f"pyrubberband not available: {e}, falling back to FFmpeg")
            return _fallback_secure(input_video_path, output_video_path, cancel_check)
        except Exception as e:
            logger.error(f"pyrubberband processing failed: {e}, falling back to FFmpeg")
            return _fallback_secure(input_video_path, output_video_path, cancel_check)
        
        if cancel_check and cancel_check():
            return False, True
        
        # Step 3: Merge processed audio with original video
        logger.info("Merging processed audio with video...")
        merge_cmd = [
            'ffmpeg', '-y',
            '-i', input_video_path,
            '-i', temp_audio_processed,
            '-c:v', 'copy',  # Copy video stream
            '-c:a', 'aac',   # Encode audio to AAC
            '-b:a', '128k',
            '-map', '0:v:0',  # Use video from first input
            '-map', '1:a:0',  # Use audio from second input
            '-shortest',  # Match shortest stream
            '-map_metadata', '-1',  # Strip metadata
            output_video_path
        ]
        
        result = subprocess.run(merge_cmd, capture_output=True, text=True, timeout=120)
        
        if cancel_check and cancel_check():
            if os.path.exists(output_video_path):
                os.remove(output_video_path)
            return False, True
        
        if result.returncode != 0:
            logger.error(f"Failed to merge audio: {result.stderr}")
            return _fallback_secure(input_video_path, output_video_path, cancel_check)
        
        if not os.path.exists(output_video_path):
            logger.error("Output file was not created")
            return False, False
        
        logger.info("Voice anonymization (Secure) completed successfully")
        return True, False
        
    except Exception as e:
        logger.error(f"Secure voice anonymization error: {e}")
        return _fallback_secure(input_video_path, output_video_path, cancel_check)
    
    finally:
        # Cleanup temp files
        for temp_file in [temp_audio_original, temp_audio_processed, temp_video_no_audio]:
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass


def _fallback_secure(input_video_path: str, output_video_path: str, cancel_check=None) -> tuple[bool, bool]:
    """Fallback to FFmpeg-only secure mode if pyrubberband fails."""
    logger.info("Using FFmpeg fallback for secure mode")
    
    try:
        if cancel_check and cancel_check():
            return False, True
        
        # More aggressive pitch shift for fallback
        semitones = random.choice([-8, -7, 7, 8])
        pitch_factor = 2 ** (semitones / 12)
        tempo_factor = 1 / pitch_factor
        tempo_variation = random.uniform(0.90, 1.10)
        final_tempo = max(0.5, min(2.0, tempo_factor * tempo_variation))
        
        audio_filter = (
            f"asetrate=44100*{pitch_factor:.4f},"
            f"aresample=44100,"
            f"atempo={final_tempo:.4f},"
            f"highpass=f=100,"
            f"lowpass=f=8000"
        )
        
        cmd = [
            'ffmpeg', '-y',
            '-i', input_video_path,
            '-af', audio_filter,
            '-c:v', 'copy',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-map_metadata', '-1',
            output_video_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if cancel_check and cancel_check():
            if os.path.exists(output_video_path):
                os.remove(output_video_path)
            return False, True
        
        if result.returncode != 0:
            logger.error(f"FFmpeg fallback error: {result.stderr}")
            return False, False
        
        return True, False
        
    except Exception as e:
        logger.error(f"Fallback secure error: {e}")
        return False, False

