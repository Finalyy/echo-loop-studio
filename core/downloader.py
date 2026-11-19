import glob
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import yt_dlp
from core.subtitle import clean_html_tags, parse_srt_content, segments_to_srt
from core.utils import find_ffmpeg, sanitize_filename

# Language code mappings and aliases
LANGUAGE_MAP = {
    "auto": [],
    "en": ["en", "en-US", "en-GB", "en-CA", "en-AU", "eng"],
    "de": ["de", "de-DE", "de-AT", "de-CH", "ger", "deu"],
    "vi": ["vi", "vi-VN", "vie"],
    "fr": ["fr", "fr-FR", "fr-CA", "fra", "fre"],
    "es": ["es", "es-ES", "es-MX", "spa"],
    "ja": ["ja", "ja-JP", "jpn"],
    "ko": ["ko", "ko-KR", "kor"],
    "zh": ["zh", "zh-Hans", "zh-Hant", "zh-CN", "zh-TW", "chi", "zho"],
    "ru": ["ru", "ru-RU", "rus"],
    "it": ["it", "it-IT", "ita"],
    "pt": ["pt", "pt-BR", "pt-PT", "por"],
}


def get_language_sub_codes(lang: str) -> List[str]:
    """Returns a list of subtitle codes to search for in yt-dlp."""
    if not lang or lang.lower() == "auto":
        return ["all"]
    lang_clean = lang.strip().lower()
    if lang_clean in LANGUAGE_MAP:
        return LANGUAGE_MAP[lang_clean]
    return [lang_clean]


def find_downloaded_subtitles(work_dir: str) -> List[str]:
    """Finds all subtitle files (.srt, .vtt) in work_dir."""
    sub_files = []
    for ext in ("*.srt", "*.vtt", "*.sub"):
        sub_files.extend(glob.glob(os.path.join(work_dir, ext)))
    return sub_files


def read_subtitle_file(file_path: str) -> str:
    """Reads a subtitle file handling various encodings (UTF-8, UTF-8-sig, CP1252, etc.)."""
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            with open(file_path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def download_media_and_subtitles(
    url: str,
    output_dir: str,
    language: str = "en",
    skip_subtitles: bool = False,
    cookies_path: Optional[str] = None,
    progress_callback=None,
) -> Tuple[str, Optional[str], str, float, str]:
    """
    Downloads audio as MP3 (96kbps) and extracts platform subtitles if available.

    Parameters:
    - url: Video URL.
    - output_dir: Directory to save downloaded files.
    - language: Desired language code ('en', 'de', 'vi', 'auto', etc.).
    - skip_subtitles: If True (e.g. prefer_ai), skips downloading platform subtitles.
    - cookies_path: Optional path to cookies.txt.
    - progress_callback: Optional callback function for status updates.

    Returns:
    - audio_path: Path to the generated .mp3 file.
    - subtitle_content: Cleaned raw SRT content (if subtitles were found), or None.
    - clean_title: Sanitized video title.
    - duration: Video duration in seconds.
    - sub_source: 'manual', 'auto', or 'none'.
    """
    os.makedirs(output_dir, exist_ok=True)
    ffmpeg_exe = find_ffmpeg()

    # Base output template using safe fixed basename inside dedicated output_dir
    base_name = "audio_download"
    out_template = os.path.join(output_dir, f"{base_name}.%(ext)s")

    # Resolve cookies file
    active_cookies = None
    if cookies_path and os.path.isfile(cookies_path):
        active_cookies = cookies_path
    elif os.path.isfile("cookies.txt"):
        active_cookies = "cookies.txt"

    sub_langs = get_language_sub_codes(language)

    # yt-dlp configuration
    ydl_opts: Dict = {
        "format": "bestaudio/best",
        "outtmpl": out_template,
        "keepvideo": False,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "96",
            }
        ],
    }

    if ffmpeg_exe:
        ydl_opts["ffmpeg_location"] = os.path.dirname(ffmpeg_exe)

    if active_cookies:
        ydl_opts["cookiefile"] = active_cookies

    # Subtitle download configuration
    if not skip_subtitles:
        ydl_opts["writesubtitles"] = True
        ydl_opts["writeautomaticsub"] = True
        ydl_opts["subtitleslangs"] = sub_langs
        ydl_opts["subtitlesformat"] = "srt/vtt/best"
        # Attempt to convert downloaded subs to srt
        ydl_opts["postprocessors"].append(
            {
                "key": "FFmpegSubtitlesConvertor",
                "format": "srt",
            }
        )

    if progress_callback:
        progress_callback("Đang kết nối và tải âm thanh / phụ đề...")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    raw_title = info.get("title", "EchoLoop_Audio")
    clean_title = sanitize_filename(raw_title)
    duration = float(info.get("duration") or 0.0)

    # Locate generated MP3 file
    expected_mp3 = os.path.join(output_dir, f"{base_name}.mp3")
    final_mp3 = os.path.join(output_dir, f"{clean_title}.mp3")

    if os.path.isfile(expected_mp3):
        if os.path.exists(final_mp3) and final_mp3 != expected_mp3:
            os.remove(final_mp3)
        os.rename(expected_mp3, final_mp3)
    else:
        # Fallback search for any mp3 in output_dir
        mp3s = glob.glob(os.path.join(output_dir, "*.mp3"))
        if mp3s:
            final_mp3 = mp3s[0]
        else:
            raise FileNotFoundError("Không tìm thấy file âm thanh .mp3 sau khi xử lý.")

    # Locate and process subtitles
    subtitle_content: Optional[str] = None
    sub_source = "none"

    if not skip_subtitles:
        sub_files = find_downloaded_subtitles(output_dir)
        if sub_files:
            # Sort to prefer manual subtitles over auto-captions
            # Auto-generated captions often contain '.auto.' in their filename
            manual_subs = [f for f in sub_files if ".auto." not in os.path.basename(f)]
            chosen_sub_file = manual_subs[0] if manual_subs else sub_files[0]
            sub_source = "manual" if manual_subs else "auto"

            raw_sub_text = read_subtitle_file(chosen_sub_file)
            segments = parse_srt_content(raw_sub_text)
            if segments:
                subtitle_content = segments_to_srt(segments)
            else:
                subtitle_content = None
                sub_source = "none"

    return final_mp3, subtitle_content, clean_title, duration, sub_source


def process_uploaded_media(
    uploaded_file_path: str,
    output_dir: str,
    progress_callback=None,
) -> Tuple[str, str, float]:
    """
    Converts any uploaded audio or video file to 96kbps MP3 for Echo Loop.
    Returns: (final_mp3_path, clean_title, duration_seconds)
    """
    from core.groq_whisper import get_audio_duration_seconds

    os.makedirs(output_dir, exist_ok=True)
    ffmpeg_exe = find_ffmpeg() or "ffmpeg"

    original_stem = Path(uploaded_file_path).stem
    clean_title = sanitize_filename(original_stem)
    out_mp3_path = os.path.join(output_dir, f"{clean_title}.mp3")

    if progress_callback:
        progress_callback("Đang chuyển đổi file âm thanh sang định dạng MP3 96kbps...")

    cmd = [
        ffmpeg_exe,
        "-y",
        "-i", uploaded_file_path,
        "-vn",
        "-codec:a", "libmp3lame",
        "-b:a", "96k",
        "-ar", "44100",
        out_mp3_path,
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    duration = get_audio_duration_seconds(out_mp3_path)
    return out_mp3_path, clean_title, duration
