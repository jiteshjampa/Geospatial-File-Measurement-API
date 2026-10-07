import os


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", "sqlite:///./aereo.db")


def get_max_upload_bytes() -> int:
    return int(os.getenv("MAX_UPLOAD_MB", "50")) * 1024 * 1024


def get_max_archive_bytes() -> int:
    return int(os.getenv("MAX_ARCHIVE_MB", "200")) * 1024 * 1024
