from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from database.base import Repository
from database.db import NoticeRepository, connect
from database.supabase_repository import SupabaseRepository


@dataclass
class RepositoryHandle:
    repository: Repository
    resource: object

    def close(self) -> None:
        close = getattr(self.resource, "close", None)
        if close:
            close()


def create_repository(sqlite_path: str | Path | None = None) -> RepositoryHandle:
    backend = os.getenv("DATABASE_BACKEND", "sqlite").strip().lower()
    if backend == "sqlite":
        connection = connect(sqlite_path) if sqlite_path is not None else connect()
        return RepositoryHandle(NoticeRepository(connection), connection)
    if backend == "supabase":
        repository = SupabaseRepository()
        return RepositoryHandle(repository, repository)
    raise RuntimeError("DATABASE_BACKEND must be 'sqlite' or 'supabase'")
