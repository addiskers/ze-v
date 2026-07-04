"""
SQLite storage for the EO Admin platform: users, contacts pool, campaigns, and
campaign_contacts. Calls stay as JSON files (store.py); they only gain a
`campaign_id` so the admin can filter/label per campaign.

Sync sqlite3 (WAL, check_same_thread=False) guarded by a lock — SQLite queries
here are tiny, so this stays off the event loop's critical path without an async
driver. Lives next to the JSON call store under DATA_DIR.
"""

import os
import sqlite3
import threading
from datetime import datetime, timezone

_DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
_DB_PATH = os.path.join(_DATA_DIR, "eo.db")

_conn: sqlite3.Connection | None = None
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        os.makedirs(_DATA_DIR, exist_ok=True)
        _conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
    return _conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    name          TEXT,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'eo_admin',   -- eo_admin | eo_agent
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contacts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT,
    phone      TEXT UNIQUE NOT NULL,                  -- E.164
    source     TEXT NOT NULL DEFAULT 'upload',        -- upload | manual | plivo
    status     TEXT NOT NULL DEFAULT 'valid',         -- valid | invalid
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_contacts_created ON contacts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_contacts_name ON contacts(name);

CREATE TABLE IF NOT EXISTS campaigns (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'scheduled', -- scheduled | live | completed | cancelled
    start_at            TEXT NOT NULL,                     -- ISO-8601 UTC
    created_by          INTEGER,
    contact_count       INTEGER NOT NULL DEFAULT 0,
    callback_delay_hours INTEGER NOT NULL DEFAULT 4,
    callback_max_per_day INTEGER NOT NULL DEFAULT 3,
    callback_days        INTEGER NOT NULL DEFAULT 1,
    -- progress counters (updated by the runner)
    done_count          INTEGER NOT NULL DEFAULT 0,
    failed_count        INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_campaigns_status ON campaigns(status);
CREATE INDEX IF NOT EXISTS idx_campaigns_created ON campaigns(created_at DESC);

CREATE TABLE IF NOT EXISTS campaign_contacts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id     INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    contact_id      INTEGER,
    phone           TEXT NOT NULL,
    name            TEXT,
    call_status     TEXT NOT NULL DEFAULT 'pending',  -- pending|calling|done|failed|no_answer
    attempts        INTEGER NOT NULL DEFAULT 0,
    day_attempts    INTEGER NOT NULL DEFAULT 0,
    day_key         TEXT,                              -- YYYY-MM-DD of last day_attempts window
    next_attempt_at TEXT,                              -- backoff/pacing gate (ISO)
    last_call_id    TEXT,
    last_attempt_at TEXT,
    last_error      TEXT,
    rsvp_outcome    TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cc_campaign ON campaign_contacts(campaign_id);
CREATE INDEX IF NOT EXISTS idx_cc_due ON campaign_contacts(call_status, next_attempt_at);
"""


def init() -> None:
    """Create tables (idempotent) + run lightweight column migrations."""
    conn = get_conn()
    with _lock:
        conn.executescript(SCHEMA)
        # additive migrations for DBs created before a column existed
        cc_cols = {r["name"] for r in conn.execute("PRAGMA table_info(campaign_contacts)").fetchall()}
        if "last_error" not in cc_cols:
            conn.execute("ALTER TABLE campaign_contacts ADD COLUMN last_error TEXT")
        conn.commit()


# ── generic helpers ──────────────────────────────────────────────────────────
def _rows(sql: str, params: tuple = ()) -> list[dict]:
    conn = get_conn()
    with _lock:
        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _one(sql: str, params: tuple = ()) -> dict | None:
    rows = _rows(sql, params)
    return rows[0] if rows else None


def _exec(sql: str, params: tuple = ()) -> int:
    conn = get_conn()
    with _lock:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid


# ── users ────────────────────────────────────────────────────────────────────
def count_users() -> int:
    r = _one("SELECT COUNT(*) c FROM users")
    return int(r["c"]) if r else 0


def create_user(username: str, name: str, password_hash: str, password_salt: str, role: str = "eo_admin") -> int:
    now = _now()
    return _exec(
        "INSERT INTO users (username, name, password_hash, password_salt, role, active, created_at, updated_at) "
        "VALUES (?,?,?,?,?,1,?,?)",
        (username, name, password_hash, password_salt, role, now, now),
    )


def get_user_by_username(username: str) -> dict | None:
    return _one("SELECT * FROM users WHERE username = ?", (username,))


def get_user(user_id: int) -> dict | None:
    return _one("SELECT * FROM users WHERE id = ?", (user_id,))


def list_users() -> list[dict]:
    return _rows("SELECT id, username, name, role, active, created_at FROM users ORDER BY created_at DESC")


def set_user_active(user_id: int, active: bool) -> None:
    _exec("UPDATE users SET active = ?, updated_at = ? WHERE id = ?", (1 if active else 0, _now(), user_id))


def update_user_password(user_id: int, password_hash: str, password_salt: str) -> None:
    _exec("UPDATE users SET password_hash = ?, password_salt = ?, updated_at = ? WHERE id = ?",
          (password_hash, password_salt, _now(), int(user_id)))


# ── contacts (global pool) ───────────────────────────────────────────────────
_CONTACT_SORTS = {"name", "phone", "source", "status", "created_at"}


def add_contact(name: str, phone: str, source: str = "manual", status: str = "valid"):
    """Upsert one contact by phone. Returns (id, created_bool)."""
    now = _now()
    existing = _one("SELECT id FROM contacts WHERE phone = ?", (phone,))
    if existing:
        _exec(
            "UPDATE contacts SET name = COALESCE(NULLIF(?, ''), name), status = ?, updated_at = ? WHERE phone = ?",
            (name or "", status, now, phone),
        )
        return existing["id"], False
    cid = _exec(
        "INSERT INTO contacts (name, phone, source, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (name, phone, source, status, now, now),
    )
    return cid, True


def bulk_upsert_contacts(rows, source: str = "upload"):
    """rows: iterable of (name, phone, status). Returns (added, updated)."""
    rows = list(rows)
    if not rows:
        return 0, 0
    now = _now()
    conn = get_conn()
    with _lock:
        existing = {r["phone"] for r in conn.execute("SELECT phone FROM contacts").fetchall()}
        conn.executemany(
            "INSERT INTO contacts (name, phone, source, status, created_at, updated_at) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(phone) DO UPDATE SET "
            "name = COALESCE(NULLIF(excluded.name, ''), contacts.name), "
            "status = excluded.status, updated_at = excluded.updated_at",
            [(nm, ph, source, st, now, now) for (nm, ph, st) in rows],
        )
        conn.commit()
    added = sum(1 for (_nm, ph, _st) in rows if ph not in existing)
    return added, len(rows) - added


def list_contacts(q=None, source=None, status=None, sort="created_at", direction="desc", limit=25, offset=0):
    where, params = [], []
    if q:
        where.append("(name LIKE ? OR phone LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    if source:
        where.append("source = ?")
        params.append(source)
    if status:
        where.append("status = ?")
        params.append(status)
    wsql = ("WHERE " + " AND ".join(where)) if where else ""
    col = sort if sort in _CONTACT_SORTS else "created_at"
    dir_sql = "ASC" if str(direction).lower() == "asc" else "DESC"
    total = _one(f"SELECT COUNT(*) c FROM contacts {wsql}", tuple(params))["c"]
    rows = _rows(
        f"SELECT * FROM contacts {wsql} ORDER BY {col} {dir_sql} LIMIT ? OFFSET ?",
        tuple(params) + (int(limit), int(offset)),
    )
    return {"items": rows, "total": int(total)}


def get_contacts_by_ids(ids):
    ids = [int(i) for i in ids if i]
    if not ids:
        return []
    ph = ",".join("?" * len(ids))
    return _rows(f"SELECT * FROM contacts WHERE id IN ({ph})", tuple(ids))


def delete_contacts(ids) -> int:
    ids = [int(i) for i in ids if i]
    if not ids:
        return 0
    ph = ",".join("?" * len(ids))
    conn = get_conn()
    with _lock:
        cur = conn.execute(f"DELETE FROM contacts WHERE id IN ({ph})", tuple(ids))
        conn.commit()
        return cur.rowcount


def count_contacts() -> int:
    r = _one("SELECT COUNT(*) c FROM contacts")
    return int(r["c"]) if r else 0


# ── campaigns ────────────────────────────────────────────────────────────────
_CAMPAIGN_SORTS = {"name", "status", "start_at", "contact_count", "created_at"}


def active_campaign() -> dict | None:
    """The one campaign currently scheduled or live (the one-active-at-a-time rule)."""
    return _one("SELECT * FROM campaigns WHERE status IN ('scheduled','live') ORDER BY created_at DESC LIMIT 1")


def create_campaign(name, start_at, created_by, callback_delay_hours,
                    callback_max_per_day, callback_days, status="scheduled") -> int:
    now = _now()
    return _exec(
        "INSERT INTO campaigns (name, status, start_at, created_by, contact_count, "
        "callback_delay_hours, callback_max_per_day, callback_days, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (name, status, start_at, created_by, 0,
         int(callback_delay_hours), int(callback_max_per_day), int(callback_days), now, now),
    )


def add_campaign_contacts(campaign_id: int, contacts) -> int:
    """contacts: iterable of rows/dicts with id, phone, name. Returns final count."""
    contacts = list(contacts)
    now = _now()
    conn = get_conn()
    with _lock:
        conn.executemany(
            "INSERT INTO campaign_contacts (campaign_id, contact_id, phone, name, call_status, "
            "attempts, day_attempts, created_at, updated_at) VALUES (?,?,?,?, 'pending', 0, 0, ?, ?)",
            [(campaign_id, c.get("id"), c.get("phone"), c.get("name"), now, now) for c in contacts],
        )
        n = conn.execute("SELECT COUNT(*) FROM campaign_contacts WHERE campaign_id = ?", (campaign_id,)).fetchone()[0]
        conn.execute("UPDATE campaigns SET contact_count = ?, updated_at = ? WHERE id = ?", (n, now, campaign_id))
        conn.commit()
    return n


def list_campaigns(q=None, sort="created_at", direction="desc", limit=50, offset=0, created_by=None):
    where, params = [], []
    if q:
        where.append("name LIKE ?")
        params.append(f"%{q}%")
    if created_by is not None:
        where.append("created_by = ?")
        params.append(int(created_by))
    wsql = ("WHERE " + " AND ".join(where)) if where else ""
    col = sort if sort in _CAMPAIGN_SORTS else "created_at"
    dir_sql = "ASC" if str(direction).lower() == "asc" else "DESC"
    total = _one(f"SELECT COUNT(*) c FROM campaigns {wsql}", tuple(params))["c"]
    rows = _rows(
        f"SELECT * FROM campaigns {wsql} ORDER BY {col} {dir_sql} LIMIT ? OFFSET ?",
        tuple(params) + (int(limit), int(offset)),
    )
    return {"items": rows, "total": int(total)}


def campaign_ids_by_owner(user_id) -> list:
    return [r["id"] for r in _rows("SELECT id FROM campaigns WHERE created_by = ?", (int(user_id),))]


def campaign_progress(campaign_id: int) -> dict:
    rows = _rows(
        "SELECT call_status, COUNT(*) n FROM campaign_contacts WHERE campaign_id = ? GROUP BY call_status",
        (int(campaign_id),),
    )
    return {r["call_status"]: r["n"] for r in rows}


def get_campaign_full(campaign_id: int) -> dict | None:
    c = get_campaign(campaign_id)
    if not c:
        return None
    c["progress"] = campaign_progress(campaign_id)
    return c


def set_campaign_status(campaign_id: int, status: str) -> None:
    _exec("UPDATE campaigns SET status = ?, updated_at = ? WHERE id = ?", (status, _now(), int(campaign_id)))


def cancel_campaign(campaign_id: int) -> bool:
    conn = get_conn()
    with _lock:
        cur = conn.execute(
            "UPDATE campaigns SET status = 'cancelled', updated_at = ? WHERE id = ? AND status IN ('scheduled','live')",
            (_now(), int(campaign_id)),
        )
        conn.commit()
        return cur.rowcount > 0


# ── campaign runner support (used by campaign_runner.py) ─────────────────────
def promote_due_campaigns(now_iso: str) -> int:
    """Flip scheduled campaigns whose start time has arrived to 'live'."""
    conn = get_conn()
    with _lock:
        cur = conn.execute(
            "UPDATE campaigns SET status = 'live', updated_at = ? WHERE status = 'scheduled' AND start_at <= ?",
            (_now(), now_iso),
        )
        conn.commit()
        return cur.rowcount


def live_campaigns() -> list[dict]:
    return _rows("SELECT * FROM campaigns WHERE status = 'live' ORDER BY created_at ASC")


def cc_pending_due(campaign_id: int, now_iso: str, limit: int) -> list[dict]:
    return _rows(
        "SELECT * FROM campaign_contacts WHERE campaign_id = ? AND call_status = 'pending' "
        "AND (next_attempt_at IS NULL OR next_attempt_at <= ?) ORDER BY id ASC LIMIT ?",
        (int(campaign_id), now_iso, int(limit)),
    )


def cc_by_status(campaign_id: int, status: str) -> list[dict]:
    return _rows(
        "SELECT * FROM campaign_contacts WHERE campaign_id = ? AND call_status = ? ORDER BY id ASC",
        (int(campaign_id), status),
    )


def list_campaign_contacts(campaign_id, status=None, limit=500, offset=0):
    where, params = ["campaign_id = ?"], [int(campaign_id)]
    if status:
        where.append("call_status = ?")
        params.append(status)
    wsql = "WHERE " + " AND ".join(where)
    total = _one(f"SELECT COUNT(*) c FROM campaign_contacts {wsql}", tuple(params))["c"]
    rows = _rows(
        f"SELECT * FROM campaign_contacts {wsql} ORDER BY id ASC LIMIT ? OFFSET ?",
        tuple(params) + (int(limit), int(offset)),
    )
    return {"items": rows, "total": int(total)}


def cc_open_count(campaign_id: int) -> int:
    r = _one(
        "SELECT COUNT(*) c FROM campaign_contacts WHERE campaign_id = ? AND call_status IN ('pending','calling')",
        (int(campaign_id),),
    )
    return int(r["c"]) if r else 0


def get_campaign_contact(cc_id) -> dict | None:
    return _one("SELECT * FROM campaign_contacts WHERE id = ?", (int(cc_id),))


def cc_update(cc_id: int, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    _exec(f"UPDATE campaign_contacts SET {cols} WHERE id = ?", tuple(fields.values()) + (int(cc_id),))


# ── campaigns: read helpers for call-log labelling ───────────────────────────
def get_campaign(campaign_id: int) -> dict | None:
    return _one("SELECT * FROM campaigns WHERE id = ?", (int(campaign_id),))


def campaign_names(ids) -> dict:
    ids = [int(i) for i in ids if i]
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    rows = _rows(f"SELECT id, name FROM campaigns WHERE id IN ({placeholders})", tuple(ids))
    return {r["id"]: r["name"] for r in rows}
