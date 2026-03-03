import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("CONTROLLER_BOT_TOKEN")
BACKEND_URL = os.getenv("BACKEND_URL")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")

if not BOT_TOKEN:
    raise RuntimeError("CONTROLLER_BOT_TOKEN not set")

if not BACKEND_URL:
    raise RuntimeError("BACKEND_URL not set")


LANG_REGIONS = [
    # СНГ
    {"code": "ru", "title": "Русский", "flag": "🇷🇺", "group": "cis"},
    {"code": "uk", "title": "Українська", "flag": "🇺🇦", "group": "cis"},
    {"code": "kk", "title": "Қазақша", "flag": "🇰🇿", "group": "cis"},
    {"code": "az", "title": "Azərbaycanca", "flag": "🇦🇿", "group": "cis"},
    {"code": "hy", "title": "Հայերեն", "flag": "🇦🇲", "group": "cis"},
    {"code": "ka", "title": "ქართული", "flag": "🇬🇪", "group": "cis"},
    {"code": "uz", "title": "Oʻzbek", "flag": "🇺🇿", "group": "cis"},
    {"code": "be", "title": "Беларуская", "flag": "🇧🇾", "group": "cis"},
    {"code": "tg", "title": "Тоҷикӣ", "flag": "🇹🇯", "group": "cis"},

    # Запад
    {"code": "en", "title": "English", "flag": "🇺🇸", "group": "west"},
    {"code": "de", "title": "Deutsch", "flag": "🇩🇪", "group": "west"},
    {"code": "fr", "title": "Français", "flag": "🇫🇷", "group": "west"},
    {"code": "es", "title": "Español", "flag": "🇪🇸", "group": "west"},
    {"code": "it", "title": "Italiano", "flag": "🇮🇹", "group": "west"},
    {"code": "pt", "title": "Português", "flag": "🇵🇹", "group": "west"},
    {"code": "pl", "title": "Polski", "flag": "🇵🇱", "group": "west"},
    {"code": "nl", "title": "Nederlands", "flag": "🇳🇱", "group": "west"},
    {"code": "cs", "title": "Čeština", "flag": "🇨🇿", "group": "west"},
    {"code": "ro", "title": "Română", "flag": "🇷🇴", "group": "west"},
    {"code": "el", "title": "Ελληνικά", "flag": "🇬🇷", "group": "west"},
    {"code": "sv", "title": "Svenska", "flag": "🇸🇪", "group": "west"},
    {"code": "da", "title": "Dansk", "flag": "🇩🇰", "group": "west"},
    {"code": "no", "title": "Norsk", "flag": "🇳🇴", "group": "west"},
    {"code": "fi", "title": "Suomi", "flag": "🇫🇮", "group": "west"},

    # Азия
    {"code": "tr", "title": "Türkçe", "flag": "🇹🇷", "group": "asia"},
    {"code": "ar", "title": "العربية", "flag": "🇸🇦", "group": "asia"},
    {"code": "he", "title": "עברית", "flag": "🇮🇱", "group": "asia"},
    {"code": "hi", "title": "हिन्दी", "flag": "🇮🇳", "group": "asia"},
    {"code": "th", "title": "ไทย", "flag": "🇹🇭", "group": "asia"},
    {"code": "vi", "title": "Tiếng Việt", "flag": "🇻🇳", "group": "asia"},
    {"code": "id", "title": "Bahasa Indonesia", "flag": "🇮🇩", "group": "asia"},
    {"code": "ms", "title": "Bahasa Melayu", "flag": "🇲🇾", "group": "asia"},
    {"code": "zh", "title": "中文", "flag": "🇨🇳", "group": "asia"},
    {"code": "ja", "title": "日本語", "flag": "🇯🇵", "group": "asia"},
    {"code": "ko", "title": "한국어", "flag": "🇰🇷", "group": "asia"},
]

REGION_BY_CODE = {x["code"]: x for x in LANG_REGIONS}
