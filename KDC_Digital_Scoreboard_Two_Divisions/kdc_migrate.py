"""Helpers for copying the ORIGINAL single KDC database into a division database.

Design rules
------------
* The original database is only ever opened READ-ONLY (``mode=ro&immutable=1``),
  so it cannot be modified, locked or have journal files written next to it.
* Nothing is ever written to an existing, non-empty destination.
* This module deliberately does not import the Flask app, so it can be used
  by the app at start-up and by the stand-alone migration script.
"""
import hashlib
import os
import sqlite3
from pathlib import Path

# Tables that belong to the original application (copied in FK-safe order).
LEGACY_TABLES = [
    "admin",
    "team",
    "game",
    "host_assignment",
    "score_submission",
    "audit_log",
]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _readonly_uri(path):
    return Path(path).resolve().as_uri() + "?mode=ro&immutable=1"


def open_legacy_readonly(path):
    """Open the original database strictly read-only."""
    return sqlite3.connect(_readonly_uri(path), uri=True)


def sqlite_file_has_tables(path):
    """True when ``path`` is an existing SQLite file that contains any table."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return False
    con = sqlite3.connect(path)
    try:
        return con.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0] > 0
    finally:
        con.close()


def copy_sqlite_database(legacy_path, dest_path):
    """Make an exact copy (schema + data) of the legacy SQLite database.

    Uses SQLite's online-backup API from a read-only source connection, so
    every row (admins, teams, games, hosts + tokens, scores, audit log, ...)
    is preserved with identical primary keys.  Refuses to touch a destination
    that already holds tables.
    """
    legacy_path = os.path.abspath(legacy_path)
    dest_path = os.path.abspath(dest_path)
    if legacy_path == dest_path:
        raise ValueError("Destination must not be the original database.")
    if not os.path.exists(legacy_path):
        raise FileNotFoundError(f"Original database not found: {legacy_path}")
    if sqlite_file_has_tables(dest_path):
        raise FileExistsError(
            f"Destination already contains data and was left untouched: {dest_path}"
        )
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    tmp_path = dest_path + ".tmp"
    if os.path.exists(tmp_path):
        os.remove(tmp_path)
    src = open_legacy_readonly(legacy_path)
    dst = sqlite3.connect(tmp_path)
    try:
        src.backup(dst)
        dst.commit()
    finally:
        dst.close()
        src.close()
    os.replace(tmp_path, dest_path)
    return dest_path


def legacy_row_counts(path):
    """Row counts of every legacy table (read-only)."""
    con = open_legacy_readonly(path)
    try:
        out = {}
        for t in LEGACY_TABLES:
            try:
                out[t] = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            except sqlite3.OperationalError:
                out[t] = None
        return out
    finally:
        con.close()


def find_legacy_db(base_dir, explicit=None):
    """Locate the original database file (env override, backup folder, instance)."""
    candidates = []
    if explicit:
        candidates.append(explicit)
    candidates += [
        os.path.join(base_dir, "original_backup", "kdc_scoreboard.db"),
        os.path.join(base_dir, "instance", "kdc_scoreboard.db"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return os.path.abspath(c)
    return None
