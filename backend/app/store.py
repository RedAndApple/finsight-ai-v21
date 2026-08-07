from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DB_PATH


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DocumentStore:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    original_name TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    mime_type TEXT,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    stage TEXT NOT NULL DEFAULT '',
                    error TEXT,
                    company TEXT,
                    document_type TEXT,
                    reporting_year INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    result_path TEXT,
                    ai_status TEXT NOT NULL DEFAULT 'not_requested'
                );
                """
            )

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        record = {
            "id": payload["id"],
            "original_name": payload["original_name"],
            "stored_path": payload["stored_path"],
            "mime_type": payload.get("mime_type"),
            "size_bytes": payload.get("size_bytes", 0),
            "status": payload.get("status", "queued"),
            "progress": payload.get("progress", 0),
            "stage": payload.get("stage", "Файл поставлен в очередь"),
            "error": None,
            "company": payload.get("company"),
            "document_type": payload.get("document_type"),
            "reporting_year": payload.get("reporting_year"),
            "created_at": now,
            "updated_at": now,
            "result_path": payload.get("result_path"),
            "ai_status": payload.get("ai_status", "not_requested"),
        }
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO documents (
                    id, original_name, stored_path, mime_type, size_bytes, status,
                    progress, stage, error, company, document_type, reporting_year,
                    created_at, updated_at, result_path, ai_status
                ) VALUES (
                    :id, :original_name, :stored_path, :mime_type, :size_bytes, :status,
                    :progress, :stage, :error, :company, :document_type, :reporting_year,
                    :created_at, :updated_at, :result_path, :ai_status
                )
                """,
                record,
            )
        return record

    def update(self, document_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = utc_now()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [document_id]
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE documents SET {assignments} WHERE id = ?", values)

    def get(self, document_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        return dict(row) if row else None

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM documents ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def delete(self, document_id: str) -> dict[str, Any] | None:
        record = self.get(document_id)
        if not record:
            return None
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        for key in ("stored_path", "result_path"):
            path = record.get(key)
            if path:
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    pass
        return record

    @staticmethod
    def write_result(path: Path, result: dict[str, Any]) -> None:
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def read_result(path: str | Path) -> dict[str, Any]:
        return json.loads(Path(path).read_text(encoding="utf-8"))


store = DocumentStore()
