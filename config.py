import os
from dotenv import load_dotenv

# Load .env file if available
load_dotenv()

# Groq API Configuration
DEFAULT_GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = "whisper-large-v3-turbo"

# Audio conversion settings
AUDIO_CODEC = "mp3"
AUDIO_BITRATE = "96k"  # High speech quality, keeps file size minimal (<25MB for ~35 min)

# Auto-merge settings for Echo Loop compatibility
DEFAULT_MIN_DURATION = 4.0   # seconds
DEFAULT_MAX_DURATION = 8.5   # seconds
DEFAULT_SILENCE_GAP = 1.5    # seconds

# Temporary workspace directory
BASE_TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_output")
os.makedirs(BASE_TEMP_DIR, exist_ok=True)

# Supported language list for the UI
LANGUAGES = [
    ("English (en)", "en"),
    ("Tiếng Việt (vi)", "vi"),
    ("Deutsch / Đức (de)", "de"),
    ("Français / Pháp (fr)", "fr"),
    ("Español / Tây Ban Nha (es)", "es"),
    ("日本語 / Nhật (ja)", "ja"),
    ("한국어 / Hàn (ko)", "ko"),
    ("中文 / Trung (zh)", "zh"),
    ("Tự động phát hiện (auto)", "auto"),
]
