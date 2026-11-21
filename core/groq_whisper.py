import math
import os
import subprocess
from typing import List, Optional
from groq import Groq
from core.subtitle import SubtitleSegment, segments_to_srt
from core.utils import find_ffmpeg

# Groq API limits files to 25MB (26,214,400 bytes). We use 23MB as safe threshold.
MAX_CHUNK_BYTES = 23 * 1024 * 1024


def get_audio_duration_seconds(audio_path: str) -> float:
    """Gets audio duration in seconds using ffprobe or ffmpeg."""
    ffmpeg_exe = find_ffmpeg()
    if not ffmpeg_exe:
        return 0.0

    ffprobe_exe = os.path.join(os.path.dirname(ffmpeg_exe), "ffprobe.exe")
    if not os.path.isfile(ffprobe_exe):
        ffprobe_exe = "ffprobe"

    try:
        cmd = [
            ffprobe_exe,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(result.stdout.strip())
    except Exception:
        # Fallback estimation: at 96kbps CBR, bytes * 8 / 96000
        size_bytes = os.path.getsize(audio_path)
        return size_bytes * 8.0 / 96000.0


def split_audio_into_chunks(audio_path: str, chunk_duration_sec: int = 900) -> List[str]:
    """
    Splits audio into smaller chunks (default 15 minutes each) using ffmpeg
    to keep each file well under Groq's 25MB limit.
    """
    ffmpeg_exe = find_ffmpeg() or "ffmpeg"
    work_dir = os.path.dirname(audio_path)
    base_name = os.path.splitext(os.path.basename(audio_path))[0]
    out_pattern = os.path.join(work_dir, f"{base_name}_chunk_%03d.mp3")

    cmd = [
        ffmpeg_exe,
        "-y",
        "-i", audio_path,
        "-f", "segment",
        "-segment_time", str(chunk_duration_sec),
        "-c", "copy",
        out_pattern,
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # Collect generated chunk files
    chunks = []
    idx = 0
    while True:
        chunk_file = os.path.join(work_dir, f"{base_name}_chunk_{idx:03d}.mp3")
        if os.path.isfile(chunk_file):
            chunks.append(chunk_file)
            idx += 1
        else:
            break

    return chunks


def transcribe_single_audio(
    client: Groq,
    audio_path: str,
    language: Optional[str] = None,
    time_offset: float = 0.0,
) -> List[SubtitleSegment]:
    """
    Transcribes a single audio file via Groq Whisper API (whisper-large-v3-turbo).
    Applies time_offset to all segment timestamps.
    """
    with open(audio_path, "rb") as f:
        file_bytes = f.read()

    prompt_text = (
        "Xin chào, đây là một đoạn hội thoại rõ ràng. "
        "Please transcribe accurately with complete sentences, proper punctuation, and natural pauses."
    )

    transcription = client.audio.transcriptions.create(
        file=(os.path.basename(audio_path), file_bytes),
        model="whisper-large-v3-turbo",
        response_format="verbose_json",
        language=language if language and language != "auto" else None,
        temperature=0.0,
        prompt=prompt_text,
    )

    # Extract segments
    segments_data = getattr(transcription, "segments", None)
    if segments_data is None and isinstance(transcription, dict):
        segments_data = transcription.get("segments", [])

    results: List[SubtitleSegment] = []
    if segments_data:
        for item in segments_data:
            if isinstance(item, dict):
                start = float(item.get("start", 0.0))
                end = float(item.get("end", 0.0))
                text = str(item.get("text", "")).strip()
            else:
                start = float(getattr(item, "start", 0.0))
                end = float(getattr(item, "end", 0.0))
                text = str(getattr(item, "text", "")).strip()

            if text and end > start:
                results.append(
                    SubtitleSegment(
                        start=start + time_offset,
                        end=end + time_offset,
                        text=text,
                    )
                )
    else:
        # Fallback if no segments returned: use entire text
        full_text = getattr(transcription, "text", "")
        if isinstance(transcription, dict):
            full_text = transcription.get("text", "")
        if full_text.strip():
            results.append(
                SubtitleSegment(
                    start=time_offset,
                    end=time_offset + 5.0,
                    text=full_text.strip(),
                )
            )

    return results


def transcribe_with_groq(
    audio_path: str,
    api_key: Optional[str] = None,
    language: str = "en",
    progress_callback=None,
) -> List[SubtitleSegment]:
    """
    Transcribes audio using Groq API model whisper-large-v3-turbo.
    Automatically handles files exceeding 25MB by splitting into chunks.

    Returns:
    - List of SubtitleSegment objects with accurate timestamps.
    """
    groq_key = (api_key or "").strip() or os.environ.get("GROQ_API_KEY", "").strip()
    if not groq_key:
        raise ValueError(
            "Chưa có Groq API Key! Vui lòng nhập khóa API trên giao diện hoặc đặt biến môi trường GROQ_API_KEY."
        )

    client = Groq(api_key=groq_key)
    file_size = os.path.getsize(audio_path)

    # Check if chunking is necessary
    if file_size > MAX_CHUNK_BYTES:
        if progress_callback:
            progress_callback("File vượt quá 25MB, đang chia nhỏ thành các đoạn để xử lý với Groq AI...")
        
        chunks = split_audio_into_chunks(audio_path, chunk_duration_sec=900)
        all_segments: List[SubtitleSegment] = []
        current_offset = 0.0

        for i, chunk in enumerate(chunks, start=1):
            if progress_callback:
                progress_callback(f"Groq Whisper AI đang xử lý đoạn {i}/{len(chunks)}...")
            
            chunk_segments = transcribe_single_audio(
                client=client,
                audio_path=chunk,
                language=language,
                time_offset=current_offset,
            )
            all_segments.extend(chunk_segments)

            # Calculate chunk duration for next offset
            chunk_duration = get_audio_duration_seconds(chunk)
            current_offset += chunk_duration

            # Clean up temp chunk file
            try:
                os.remove(chunk)
            except OSError:
                pass

        return all_segments
    else:
        if progress_callback:
            progress_callback("Groq Whisper AI (whisper-large-v3-turbo) đang nhận diện âm thanh...")

        return transcribe_single_audio(
            client=client,
            audio_path=audio_path,
            language=language,
            time_offset=0.0,
        )
