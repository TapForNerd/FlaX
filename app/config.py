import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    APP_NAME = os.getenv("APP_NAME", "FlaX")
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///app.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "afb_session")
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
    X_API_BASE_URL = os.getenv("X_API_BASE_URL", "https://api.x.com/2")
    X_BEARER_TOKEN = os.getenv("X_BEARER_TOKEN")
    X_CLIENT_ID = os.getenv("X_CLIENT_ID")
    X_CLIENT_SECRET = os.getenv("X_CLIENT_SECRET")
    X_APP_NAME = os.getenv("X_APP_NAME")
    X_REDIRECT_URI = os.getenv("X_REDIRECT_URI")
    X_ADMIN_USERNAMES = os.getenv("X_ADMIN_USERNAMES", "")
    VERSION = os.getenv("VERSION", "0.1.0")
    PORT = os.getenv("PORT", "5000")
