import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(parents=True, exist_ok=True)


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "sqlite:///panel.db",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    JSON_AS_ASCII = False
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "ChangeMe123!")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    ZERO_API_BASE = os.getenv("ZERO_API_BASE", "https://zero.withzeng.de").rstrip("/")
    ZERO_API_KEY = os.getenv("ZERO_API_KEY", "")
    ZERO_API_TIMEOUT = float(os.getenv("ZERO_API_TIMEOUT", "10"))
    ZERO_DRY_RUN = os.getenv("ZERO_DRY_RUN", "true").strip().lower() != "false"
    ZERO_DEFAULT_FORWARD_ENDPOINT_IDS = [
        int(item.strip())
        for item in os.getenv("ZERO_DEFAULT_FORWARD_ENDPOINT_IDS", "").split(",")
        if item.strip().isdigit()
    ]
    ZERO_DEFAULT_CHAIN_FIXED_HOPS_NUM = int(os.getenv("ZERO_DEFAULT_CHAIN_FIXED_HOPS_NUM", "2"))
