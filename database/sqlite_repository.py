"""Explicit SQLite adapter; database.db remains a compatibility import."""

from database.db import NoticeRepository, connect

SQLiteRepository = NoticeRepository

__all__ = ["SQLiteRepository", "NoticeRepository", "connect"]
