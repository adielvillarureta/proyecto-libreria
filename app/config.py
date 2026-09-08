# config.py
import os
from dotenv import load_dotenv

load_dotenv(verbose=True)

# Base de datos
DB_HOST = os.getenv('DB_HOST')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_NAME = os.getenv('DB_NAME')
SECRET_KEY = os.getenv('SECRET_KEY', 'clave_secreta_segura')

# API Perú
API_PERU_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJlbWFpbCI6ImkyNTExOTExQGNvbnRpbmVudGFsLmVkdS5wZSJ9.fNVvZJpJitDHY9c3Hrr2T7iLhfZ-NhyJ90Ynh5Delys"

# Email
EMAIL_HOST = "smtp-librospe.alwaysdata.net"
EMAIL_PORT = 587
EMAIL_USER = "librospe@alwaysdata.net"
EMAIL_PASSWORD = "Ventas2026!"
EMAIL_FROM = "librospe@alwaysdata.net"

# Uploads
UPLOAD_FOLDER = "static/img/productos"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

# SQLAlchemy
SQLALCHEMY_DATABASE_URI = "mysql+pymysql://librospe:75535870@mysql-librospe.alwaysdata.net/librospe_db"
SQLALCHEMY_TRACK_MODIFICATIONS = False
SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"ssl": {"ssl_mode": "REQUIRED"}}}