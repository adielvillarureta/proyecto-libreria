# app/config.py
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "clave_secreta_segura")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "mysql+pymysql://librospe:75535870@mysql-librospe.alwaysdata.net/librospe_db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"ssl": {"ssl_mode": "REQUIRED"}}}

    UPLOAD_FOLDER = "static/img/productos"
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB

    # Email
    EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp-librospe.alwaysdata.net")
    EMAIL_PORT = int(os.getenv("EMAIL_PORT", 587))
    EMAIL_USER = os.getenv("EMAIL_USER", "librospe@alwaysdata.net")
    EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "Ventas2026!")
    EMAIL_FROM = os.getenv("EMAIL_FROM", "librospe@alwaysdata.net")

    # API Perú
    API_PERU_TOKEN = os.getenv("API_PERU_TOKEN", "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJlbWFpbCI6ImkyNTExOTExQGNvbnRpbmVudGFsLmVkdS5wZSJ9.fNVvZJpJitDHY9c3Hrr2T7iLhfZ-NhyJ90Ynh5Delys")