"""
Configuration for the Multilingual Interview System.
Edit these settings to match your environment.
"""
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # Flask
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-to-a-random-string-in-production")

    # Database
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(BASE_DIR, 'carringbush.db')}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Student files root folder
    STUDENT_FILES_DIR = os.path.join(BASE_DIR, "student_files")

    # Whisper model size: "tiny", "base", "small", "medium", "large"
    # "base" is a good balance of speed and accuracy for most Macs
    # "small" is better accuracy but slower
    WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base")

    # Translation service
    # Set to a LibreTranslate instance URL, or "local" to use the bundled one
    LIBRETRANSLATE_URL = os.environ.get("LIBRETRANSLATE_URL", "https://libretranslate.com")

    # AI document generation
    # Set your Anthropic API key here or as an environment variable
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

    # If no API key, the system will still work but will use simple
    # template-based document generation instead of AI-powered generation
    USE_AI_GENERATION = bool(ANTHROPIC_API_KEY)

    # Upload settings
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB max upload

    # Supported languages (ISO 639-1 codes)
    # These are the priority languages from the questionnaire
    SUPPORTED_LANGUAGES = {
        "en": "English",
        "tl": "Filipino (Tagalog)",
        "vi": "Vietnamese",
        "th": "Thai",
        "ar": "Arabic",
        "am": "Amharic",
        "fa": "Farsi (Persian)",
        "hi": "Hindi",
        "ur": "Urdu",
        "he": "Hebrew",
        "lo": "Lao",
        "zh": "Chinese (Mandarin)",
        "ko": "Korean",
        "ja": "Japanese",
        "ms": "Malay",
        "my": "Burmese",
        "ne": "Nepali",
        "pa": "Punjabi",
        "ta": "Tamil",
        "bn": "Bengali",
        "so": "Somali",
        "sw": "Swahili",
        "tr": "Turkish",
        "ru": "Russian",
        "es": "Spanish",
        "fr": "French",
        "pt": "Portuguese",
    }

    # Debug mode
    DEBUG = os.environ.get("FLASK_DEBUG", "true").lower() == "true"

    # English level options
    ENGLISH_LEVELS = [
        ("starting", "Just starting out"),
        ("basic", "Basic conversation"),
        ("comfortable", "Comfortable"),
        ("fluent", "Fluent"),
    ]

    # Organisation details (update once confirmed)
    ORG_NAME = os.environ.get("ORG_NAME", "[Organisation Name]")
    ORG_CONTACT = os.environ.get("ORG_CONTACT", "[Contact Details]")

    # Interview guide (placeholder — will be populated dynamically per language)
    INTERVIEW_GUIDE = {}
