# app/config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-cambiar-en-produccion")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"ssl": {"ssl_mode": "REQUIRED"}}}

    UPLOAD_FOLDER = "static/img/productos"
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB

    # Email
    EMAIL_HOST = os.getenv("EMAIL_HOST", "")
    EMAIL_PORT = int(os.getenv("EMAIL_PORT", 587))
    EMAIL_USER = os.getenv("EMAIL_USER", "")
    EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
    EMAIL_FROM = os.getenv("EMAIL_FROM", EMAIL_USER)

    # API Perú
    API_PERU_TOKEN = os.getenv("API_PERU_TOKEN", "")

    # URL pública de la aplicación (ngrok, dominio, etc.)
    # Se usa para construir los links de OAuth y de correos.
    BASE_URL = os.getenv("BASE_URL", "").rstrip("/")

    # OAuth social
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "")
    FACEBOOK_APP_ID = os.getenv("FACEBOOK_APP_ID", "")
    FACEBOOK_APP_SECRET = os.getenv("FACEBOOK_APP_SECRET", "")
    FACEBOOK_REDIRECT_URI = os.getenv("FACEBOOK_REDIRECT_URI", "")