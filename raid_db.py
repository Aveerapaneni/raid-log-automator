"""US-9: SQLite persistence layer for the RAID Log Automator.

This is the project's own local store -- auto-created and seeded from
raid_mock_data.json the first time any command runs against a path where
it doesn't exist yet (Section 13.3). The seed file itself is never
written to; it stays the canonical, portable mock dataset.

Only raw/input fields from the Section 5 schema are stored, plus the
three fields v1's user stories actually transition -- Status, Category,
Materialized. Priority and Days Open are never persisted; every other
module still computes them fresh on read (Section 13.3).

There is deliberately no delete/remove function here -- the "never
delete" guarantee (US-7) holds at the storage layer by construction,
since no code path in this module can issue a DELETE against the
entries table.
"""

import json
import os
import sqlite3
from contextlib import closing

DEFAULT_DB_PATH = "raid_log.db"

FIELDS = [
    "id",
    "category",
    "description",
    "date_raised",
    "owner",
    "probability",
    "impact",
    "mitigation_plan",
    "start_date",
    "status",
    "materialized",
    "dependency_links",
    "blocked_by",
    "target_date",
    "last_updated",
]

LIST_FIELDS = {"dependency_links", "blocked_by"}


def ensure_db(db_path, seed_path):
    """Creates and seeds the database from seed_path if db_path doesn't
    exist yet. No-op if it already exists -- this never re-seeds a live
    database (that's reset_db's job, US-10)."""
    if os.path.exists(db_path):
        return
    with open(seed_path) as f:
        dataset = json.load(f)
    with closing(sqlite3.connect(db_path)) as conn:
        _create_table(conn)
        for entry in dataset["entries"]:
            _insert(conn, entry)
        conn.commit()


def _create_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entries (
            id TEXT PRIMARY KEY,
            category TEXT,
            description TEXT,
            date_raised TEXT,
            owner TEXT,
            probability INTEGER,
            impact INTEGER,
            mitigation_plan TEXT,
            start_date TEXT,
            status TEXT,
            materialized INTEGER,
            dependency_links TEXT,
            blocked_by TEXT,
            target_date TEXT,
            last_updated TEXT
        )
        """
    )


def _insert(conn, entry):
    values = [_encode(field, entry.get(field)) for field in FIELDS]
    placeholders = ", ".join("?" for _ in FIELDS)
    columns = ", ".join(FIELDS)
    conn.execute(f"INSERT INTO entries ({columns}) VALUES ({placeholders})", values)


def _encode(field, value):
    if field in LIST_FIELDS:
        return json.dumps(value or [])
    if field == "materialized" and value is not None:
        return int(bool(value))
    return value


def _decode(field, value):
    if field in LIST_FIELDS:
        return json.loads(value) if value is not None else []
    if field == "materialized" and value is not None:
        return bool(value)
    return value


def load_entries(db_path):
    """Returns all entries as plain dicts matching the same shape used
    everywhere else in the codebase, ordered by id for stable output."""
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"SELECT {', '.join(FIELDS)} FROM entries ORDER BY id").fetchall()
        return [{field: _decode(field, row[field]) for field in FIELDS} for row in rows]


def update_fields(db_path, entry_id, **fields):
    """Writes back only the given fields for entry_id -- used for
    Status, Category, and Materialized, the only fields any v1 story
    computes (Section 13.3). No-op if fields is empty."""
    if not fields:
        return
    assignments = ", ".join(f"{k} = ?" for k in fields)
    values = [_encode(k, v) for k, v in fields.items()]
    values.append(entry_id)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(f"UPDATE entries SET {assignments} WHERE id = ?", values)
        conn.commit()


def reset_db(db_path, seed_path):
    """US-10: discard all persisted state and reseed fresh from
    seed_path. This is the one place in the codebase that removes a
    database file -- an explicit, whole-store reset the PM asked for by
    name, never a side effect of any other command (Section 13.4). It
    is unrelated to the never-delete guarantee (US-7), which is about
    individual entries staying in the dataset, not about this file.
    seed_path itself is only ever read here, never written to."""
    if os.path.exists(db_path):
        os.remove(db_path)
    ensure_db(db_path, seed_path)
