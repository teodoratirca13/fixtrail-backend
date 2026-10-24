"""Stratul de persistență: SQLite simplu, fără ORM.

De ce fără ORM (SQLAlchemy): avem 3 tabele și 6 ore de hackathon. sqlite3 e
în biblioteca standard, iar SQL-ul scris direct e ușor de citit și de depanat.
Excel-ul e doar sursă de import; „sursa de adevăr” după import e baza asta.
"""
import json
import sqlite3
import threading
from contextlib import contextmanager

from .config import DB_PATH, DEFAULT_SETTINGS

# Scheduler-ul rulează în alt thread decât request-urile; un lock simplu
# evită „database is locked” la scrieri simultane.
_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY,
    data_deschiderii TEXT,
    canal TEXT,
    categorie TEXT,
    functionalitate TEXT,
    titlu TEXT,
    descriere TEXT,
    pasi_verificare TEXT,
    severitate TEXT,
    severitate_sursa TEXT DEFAULT 'excel',
    nr_raportari INTEGER DEFAULT 0,
    versiune_raportata TEXT,
    status TEXT,
    versiune_fix TEXT,
    data_livrare_fix TEXT,
    echipa TEXT,
    tichet_legat TEXT,
    cluster_id TEXT,
    redeschis_de_agent INTEGER DEFAULT 0,
    ultima_verificare TEXT,      -- JSON: {verdict, data, versiuneTestata, raportId}
    plan_json TEXT,              -- planul agentului, cache (generat o singură dată)
    ordine INTEGER               -- ordinea din Excel, pentru afișare stabilă
);
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    ticket_id TEXT,
    data TEXT,
    payload TEXT                 -- JSON complet al raportului (modelul Raport)
);
CREATE INDEX IF NOT EXISTS idx_reports_ticket ON reports(ticket_id, data);
CREATE TABLE IF NOT EXISTS clusters (
    id TEXT PRIMARY KEY,
    titlu TEXT
);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # rânduri accesibile după numele coloanei
    return conn


@contextmanager
def tx():
    """Context manager pentru o tranzacție: commit la final, rollback la eroare."""
    with _lock:
        conn = _connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def init_db() -> None:
    with tx() as c:
        c.executescript(SCHEMA)
        for k, v in DEFAULT_SETTINGS.items():
            c.execute("INSERT OR IGNORE INTO kv(key, value) VALUES (?, ?)", (f"settings.{k}", json.dumps(v)))


def kv_get(key: str, default=None):
    with tx() as c:
        row = c.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def kv_set(key: str, value) -> None:
    with tx() as c:
        c.execute("INSERT OR REPLACE INTO kv(key, value) VALUES (?, ?)", (key, json.dumps(value)))
