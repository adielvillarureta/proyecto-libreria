import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'clave_secreta_segura')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'mysql+pymysql://user:pass@host/db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"ssl": {"ssl_mode": "REQUIRED"}}}
    UPLOAD_FOLDER = "static/img/productos"
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
    # Email
    EMAIL_HOST = os.environ.get('EMAIL_HOST')
    EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
    EMAIL_USER = os.environ.get('EMAIL_USER')
    EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD')
    EMAIL_FROM = os.environ.get('EMAIL_FROM')
    # API PERU
    API_PERU_TOKEN = os.environ.get('API_PERU_TOKEN')