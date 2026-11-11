"""SQLite persistence for notes, encrypted content, revisions, and recovery."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator


DEFAULT_CATEGORIES = (
    "College Notes",
    "Programming",
    "Assignments",
    "Personal",
    "Important",
)


def timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class SmartPadStore:
    """Small SQLite repository; plaintext and encrypted note content are blobs."""

    def __init__(self, path: str | None = None) -> None:
        default_dir = Path.home() / ".smartpad"
        default_dir.mkdir(parents=True, exist_ok=True)
        self.path = path or str(default_dir / "smartpad.sqlite3")
        self._initialize()

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS categories (
                    name TEXT PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    content BLOB NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT 'College Notes',
                    favorite INTEGER NOT NULL DEFAULT 0,
                    encrypted INTEGER NOT NULL DEFAULT 0,
                    salt BLOB,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_opened TEXT
                );
                CREATE TABLE IF NOT EXISTS revisions (
                    id INTEGER PRIMARY KEY,
                    note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
                    content BLOB NOT NULL,
                    encrypted INTEGER NOT NULL DEFAULT 0,
                    salt BLOB,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS file_revisions (
                    id INTEGER PRIMARY KEY,
                    path TEXT NOT NULL,
                    content BLOB NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recovery (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    note_id INTEGER,
                    content BLOB NOT NULL,
                    encrypted INTEGER NOT NULL DEFAULT 0,
                    salt BLOB,
                    saved_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            revision_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(revisions)")
            }
            if "encrypted" not in revision_columns:
                connection.execute(
                    "ALTER TABLE revisions ADD COLUMN encrypted INTEGER NOT NULL DEFAULT 0"
                )
            if "salt" not in revision_columns:
                connection.execute("ALTER TABLE revisions ADD COLUMN salt BLOB")
            for category in DEFAULT_CATEGORIES:
                connection.execute(
                    "INSERT OR IGNORE INTO categories(name) VALUES (?)", (category,)
                )

    @staticmethod
    def _note(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def list_categories(self) -> list[str]:
        with self._connect() as connection:
            return [
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM categories ORDER BY name COLLATE NOCASE"
                )
            ]

    def add_category(self, name: str) -> None:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("Category name cannot be empty.")
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO categories(name) VALUES (?)", (cleaned,)
            )

    def list_notes(self, query: str = "", category: str | None = None) -> list[dict[str, Any]]:
        clauses = ["(title LIKE ? OR (encrypted = 0 AND CAST(content AS TEXT) LIKE ?))"]
        params: list[Any] = [f"%{query}%", f"%{query}%"]
        if category and category != "All Notes":
            clauses.append("category = ?")
            params.append(category)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT id, title, category, favorite, encrypted, updated_at, last_opened "
                f"FROM notes WHERE {' AND '.join(clauses)} "
                "ORDER BY favorite DESC, COALESCE(last_opened, updated_at) DESC",
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    def get_note(self, note_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            return self._note(
                connection.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
            )

    def create_note(
        self,
        title: str,
        content: bytes | str = "",
        category: str = "College Notes",
        encrypted: bool = False,
        salt: bytes | None = None,
    ) -> int:
        now = timestamp()
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT INTO notes
                   (title, content, category, encrypted, salt, created_at, updated_at, last_opened)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (title.strip() or "Untitled", content, category, int(encrypted), salt, now, now, now),
            )
            return int(cursor.lastrowid)

    def update_note(
        self,
        note_id: int,
        title: str,
        content: bytes | str,
        category: str,
        encrypted: bool,
        salt: bytes | None,
        keep_revision: bool = True,
    ) -> None:
        now = timestamp()
        with self._connect() as connection:
            if keep_revision:
                old = connection.execute(
                    "SELECT content FROM notes WHERE id = ?", (note_id,)
                ).fetchone()
                if old and old["content"] != content and old["content"]:
                    connection.execute(
                        """INSERT INTO revisions(note_id, content, encrypted, salt, created_at)
                           SELECT id, content, encrypted, salt, ? FROM notes WHERE id = ?""",
                        (now, note_id),
                    )
                    connection.execute(
                        """DELETE FROM revisions WHERE note_id = ? AND id NOT IN
                           (SELECT id FROM revisions WHERE note_id = ?
                            ORDER BY id DESC LIMIT 100)""",
                        (note_id, note_id),
                    )
            connection.execute(
                """UPDATE notes SET title = ?, content = ?, category = ?, encrypted = ?,
                   salt = ?, updated_at = ? WHERE id = ?""",
                (title.strip() or "Untitled", content, category, int(encrypted), salt, now, note_id),
            )

    def rename_note(self, note_id: int, title: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE notes SET title = ?, updated_at = ? WHERE id = ?",
                (title.strip(), timestamp(), note_id),
            )

    def delete_note(self, note_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM notes WHERE id = ?", (note_id,))

    def set_favorite(self, note_id: int, favorite: bool) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE notes SET favorite = ?, updated_at = ? WHERE id = ?",
                (int(favorite), timestamp(), note_id),
            )

    def mark_opened(self, note_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE notes SET last_opened = ? WHERE id = ?", (timestamp(), note_id)
            )

    def revisions(self, note_id: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT id, created_at, encrypted FROM revisions "
                    "WHERE note_id = ? ORDER BY id DESC",
                    (note_id,),
                )
            ]

    def get_revision(self, revision_id: int) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT content, encrypted, salt FROM revisions WHERE id = ?", (revision_id,)
            ).fetchone()
            if row is None:
                raise KeyError("The selected revision no longer exists.")
            return dict(row)

    def clear_revisions(self, note_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM revisions WHERE note_id = ?", (note_id,))

    def clear_file_revisions(self, path: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM file_revisions WHERE path = ?", (path,))

    def add_file_revision(self, path: str, content: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO file_revisions(path, content, created_at) VALUES (?, ?, ?)",
                (path, content, timestamp()),
            )
            connection.execute(
                """DELETE FROM file_revisions WHERE path = ? AND id NOT IN
                   (SELECT id FROM file_revisions WHERE path = ? ORDER BY id DESC LIMIT 50)""",
                (path, path),
            )

    def file_revisions(self, path: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT id, created_at FROM file_revisions WHERE path = ? "
                    "ORDER BY id DESC",
                    (path,),
                )
            ]

    def get_file_revision(self, revision_id: int) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT content FROM file_revisions WHERE id = ?", (revision_id,)
            ).fetchone()
            if row is None:
                raise KeyError("The selected document version no longer exists.")
            value = row["content"]
            return value.decode("utf-8") if isinstance(value, bytes) else value

    def save_recovery(
        self,
        note_id: int | None,
        content: bytes | str,
        encrypted: bool = False,
        salt: bytes | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO recovery(id, note_id, content, encrypted, salt, saved_at)
                   VALUES (1, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET note_id=excluded.note_id,
                   content=excluded.content, encrypted=excluded.encrypted,
                   salt=excluded.salt, saved_at=excluded.saved_at""",
                (note_id, content, int(encrypted), salt, timestamp()),
            )

    def get_recovery(self) -> dict[str, Any] | None:
        with self._connect() as connection:
            return self._note(
                connection.execute("SELECT * FROM recovery WHERE id = 1").fetchone()
            )

    def clear_recovery(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM recovery WHERE id = 1")

    def get_setting(self, key: str, default: str = "") -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
