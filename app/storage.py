from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


MESSAGE_STATUSES = ("pending", "streaming", "completed", "failed")
GENERATION_STATUSES = ("pending", "streaming", "completed", "failed")

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'completed'
        CHECK(status IN ('pending', 'streaming', 'completed', 'failed')),
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS generation_jobs (
    request_id TEXT PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    assistant_message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'streaming', 'completed', 'failed')),
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
ON messages(conversation_id, id);

CREATE INDEX IF NOT EXISTS idx_generation_jobs_conversation_id
ON generation_jobs(conversation_id, assistant_message_id);
"""


class Storage:
    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            self._ensure_column(
                connection,
                "messages",
                "status",
                """
                ALTER TABLE messages
                ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'
                CHECK(status IN ('pending', 'streaming', 'completed', 'failed'))
                """,
            )
            self._ensure_column(
                connection,
                "messages",
                "error",
                "ALTER TABLE messages ADD COLUMN error TEXT",
            )

    def _ensure_column(
        self,
        connection: sqlite3.Connection,
        table_name: str,
        column_name: str,
        alter_statement: str,
    ) -> None:
        columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name not in columns:
            connection.execute(alter_statement)

    def list_conversations(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, title, created_at, updated_at
                FROM conversations
                ORDER BY updated_at DESC, id DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_conversation(self, conversation_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, title, created_at, updated_at
                FROM conversations
                WHERE id = ?
                """,
                (conversation_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_messages(self, conversation_id: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, role, content, status, error, created_at
                FROM messages
                WHERE conversation_id = ?
                ORDER BY id ASC
                """,
                (conversation_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_message(self, message_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, conversation_id, role, content, status, error, created_at
                FROM messages
                WHERE id = ?
                """,
                (message_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_model_messages(
        self, conversation_id: int, before_message_id: int | None = None
    ) -> list[dict[str, str]]:
        query = """
            SELECT role, content
            FROM messages
            WHERE conversation_id = ?
              AND status != 'failed'
        """
        parameters: list[Any] = [conversation_id]
        if before_message_id is not None:
            query += " AND id < ?"
            parameters.append(before_message_id)
        query += " ORDER BY id ASC"

        with self.connect() as connection:
            rows = connection.execute(query, tuple(parameters)).fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in rows]

    def create_conversation(self, title: str) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO conversations (title) VALUES (?)",
                (title,),
            )
            return int(cursor.lastrowid)

    def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        *,
        status: str = "completed",
        error: str | None = None,
    ) -> int:
        if status not in MESSAGE_STATUSES:
            raise ValueError(f"Unsupported message status: {status}")

        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO messages (conversation_id, role, content, status, error)
                VALUES (?, ?, ?, ?, ?)
                """,
                (conversation_id, role, content, status, error),
            )
            self._touch_conversation(connection, conversation_id)
            return int(cursor.lastrowid)

    def update_message(
        self,
        message_id: int,
        *,
        content: str | None = None,
        status: str | None = None,
        error: str | None = None,
    ) -> None:
        assignments: list[str] = []
        parameters: list[Any] = []

        if content is not None:
            assignments.append("content = ?")
            parameters.append(content)
        if status is not None:
            if status not in MESSAGE_STATUSES:
                raise ValueError(f"Unsupported message status: {status}")
            assignments.append("status = ?")
            parameters.append(status)

        if error is None:
            assignments.append("error = NULL")
        else:
            assignments.append("error = ?")
            parameters.append(error)

        if not assignments:
            return

        parameters.append(message_id)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE messages SET {', '.join(assignments)} WHERE id = ?",
                tuple(parameters),
            )
            self._touch_conversation_for_message(connection, message_id)

    def append_message_chunk(self, message_id: int, chunk: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE messages
                SET content = content || ?, status = 'streaming', error = NULL
                WHERE id = ?
                """,
                (chunk, message_id),
            )
            self._touch_conversation_for_message(connection, message_id)

    def create_generation_job(
        self,
        request_id: str,
        conversation_id: int,
        user_message_id: int,
        assistant_message_id: int,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO generation_jobs (
                    request_id,
                    conversation_id,
                    user_message_id,
                    assistant_message_id
                )
                VALUES (?, ?, ?, ?)
                """,
                (request_id, conversation_id, user_message_id, assistant_message_id),
            )

    def get_generation_job(self, request_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    request_id,
                    conversation_id,
                    user_message_id,
                    assistant_message_id,
                    status,
                    error,
                    created_at,
                    updated_at
                FROM generation_jobs
                WHERE request_id = ?
                """,
                (request_id,),
            ).fetchone()
        return dict(row) if row else None

    def update_generation_job(
        self,
        request_id: str,
        *,
        status: str,
        error: str | None = None,
    ) -> None:
        if status not in GENERATION_STATUSES:
            raise ValueError(f"Unsupported generation status: {status}")

        with self.connect() as connection:
            connection.execute(
                """
                UPDATE generation_jobs
                SET status = ?, error = ?, updated_at = CURRENT_TIMESTAMP
                WHERE request_id = ?
                """,
                (status, error, request_id),
            )

    def mark_incomplete_generations_failed(self) -> None:
        error = "Generation interrupted by server restart."
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT assistant_message_id
                FROM generation_jobs
                WHERE status IN ('pending', 'streaming')
                """
            ).fetchall()
            if not rows:
                return

            connection.execute(
                """
                UPDATE generation_jobs
                SET status = 'failed', error = ?, updated_at = CURRENT_TIMESTAMP
                WHERE status IN ('pending', 'streaming')
                """,
                (error,),
            )
            assistant_ids = [row["assistant_message_id"] for row in rows]
            placeholders = ",".join("?" for _ in assistant_ids)
            connection.execute(
                f"""
                UPDATE messages
                SET status = 'failed', error = ?
                WHERE id IN ({placeholders})
                  AND status IN ('pending', 'streaming')
                """,
                (error, *assistant_ids),
            )

    def conversation_exists(self, conversation_id: int) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        return row is not None

    def _touch_conversation(self, connection: sqlite3.Connection, conversation_id: int) -> None:
        connection.execute(
            """
            UPDATE conversations
            SET updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (conversation_id,),
        )

    def _touch_conversation_for_message(
        self, connection: sqlite3.Connection, message_id: int
    ) -> None:
        row = connection.execute(
            "SELECT conversation_id FROM messages WHERE id = ?",
            (message_id,),
        ).fetchone()
        if row is not None:
            self._touch_conversation(connection, int(row["conversation_id"]))


def build_conversation_title(prompt: str, max_length: int = 60) -> str:
    normalized = " ".join(prompt.split())
    if len(normalized) <= max_length:
        return normalized or "New conversation"
    return f"{normalized[: max_length - 1].rstrip()}…"
