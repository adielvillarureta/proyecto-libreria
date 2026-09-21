# app/config.py
import os
from dotenv import load_dotenv

load_dotenv()

_DB_URI = os.getenv("DATABASE_URL")
if not _DB_URI:
    _DB_URI = (
        f"mysql+pymysql://{os.getenv('DB_USER', '')}:{os.getenv('DB_PASSWORD', '')}"
        f"@{os.getenv('DB_HOST', 'localhost')}/{os.getenv('DB_NAME', '')}"
    )


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "cambiar-en-produccion")
    SQLALCHEMY_DATABASE_URI = _DB_URI
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"ssl": {"ssl_mode": "REQUIRED"}}}

    UPLOAD_FOLDER = os.getenv(
        "UPLOAD_FOLDER",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "img", "productos"),
    )
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB

    # Email
    EMAIL_HOST = os.getenv("EMAIL_HOST", "")
    EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
    EMAIL_USER = os.getenv("EMAIL_USER", "")
    EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
    EMAIL_FROM = os.getenv("EMAIL_FROM", os.getenv("EMAIL_USER", ""))

    # API Perú (DNI/RUC)
    API_PERU_TOKEN = os.getenv("API_PERU_TOKEN", "")
