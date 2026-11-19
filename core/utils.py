import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import Optional

def find_ffmpeg() -> Optional[str]:
    """
    Locates the ffmpeg executable on the system.
    Checks PATH first, then well-known locations on Windows.
    """
    # 1. Standard PATH
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        return ffmpeg_path

    # 2. Check Windows known paths
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        candidates = [
            # Winget Gyan FFmpeg
            os.path.join(
                local_app_data,
                "Microsoft",
                "WinGet",
                "Packages",
                "Gyan.FFmpeg.Essentials_Microsoft.Winget.Source_8wekyb3d8bbwe",
                "ffmpeg-9.0.1-essentials_build",
                "bin",
                "ffmpeg.exe",
            ),
            # ShareX FFmpeg
            r"C:\Program Files\ShareX\ffmpeg.exe",
            # Chocolatey
            r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
            # Scoop
            os.path.join(os.environ.get("USERPROFILE", ""), "scoop", "shims", "ffmpeg.exe"),
        ]
        for candidate in candidates:
            if os.path.isfile(candidate):
                # Ensure the parent directory is added to os.environ["PATH"]
                bin_dir = os.path.dirname(candidate)
                if bin_dir not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
                return candidate

    return None


def sanitize_filename(name: str, max_length: int = 60) -> str:
    """
    Cleans and sanitizes a string to make it safe for filenames across Windows,
    macOS, Android, and Linux filesystems.
    Removes invalid characters, trims whitespace, and limits length.
    """
    if not name:
        return "EchoLoop_Audio"

    # Remove illegal filename characters: < > : " / \ | ? *
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    # Replace sequences of whitespace, underscores, and dashes with single space
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Strip dangerous leading/trailing characters
    cleaned = cleaned.strip(". ")

    if not cleaned:
        cleaned = "EchoLoop_Audio"

    # Limit maximum length while keeping words intact if possible
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip()

    return cleaned


def create_echoloop_zip(mp3_path: str, srt_path: str, zip_path: str) -> str:
    """
    Packages .mp3 and .srt into a single ZIP archive.
    Both files are stored at the root of the ZIP with identical basenames
    so Echo Loop can automatically pair them upon import.
    """
    mp3_file = Path(mp3_path)
    srt_file = Path(srt_path)

    if not mp3_file.exists():
        raise FileNotFoundError(f"Audio file not found: {mp3_path}")
    if not srt_file.exists():
        raise FileNotFoundError(f"Subtitle file not found: {srt_path}")

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(mp3_path, arcname=mp3_file.name)
        zf.write(srt_path, arcname=srt_file.name)

    return zip_path
