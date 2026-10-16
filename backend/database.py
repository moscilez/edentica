"""PostgreSQL is the only database used by the application server."""
import os
from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

ROOT = Path(__file__).resolve().parent.parent


class Database:
    def __init__(self, url=None):
        url = url or os.getenv("DATABASE_URL")
        if not url or not url.startswith(("postgresql://", "postgres://")):
            raise RuntimeError("Настройте DATABASE_URL для PostgreSQL в .env")
        self.pool = ConnectionPool(url, min_size=1, max_size=8, timeout=10,
                                   kwargs={"row_factory": dict_row, "connect_timeout": 5}, open=False)

    def open(self):
        self.pool.open(wait=True, timeout=15)
        # One process owns the agent scheduler. A second instance must fail before
        # it can mark another instance's running jobs as interrupted.
        self.guard = self.pool.getconn()
        self.guard.autocommit = True
        locked = self.guard.execute("SELECT pg_try_advisory_lock(421572019) AS locked").fetchone()["locked"]
        if not locked:
            self.pool.putconn(self.guard)
            self.guard = None
            raise RuntimeError("Другая копия Edentica уже использует эту БД")
        with self.pool.connection() as connection:
            connection.execute((ROOT / "backend/schema.sql").read_text(encoding="utf-8"))
            connection.execute("""UPDATE program_projects SET document=jsonb_set(
                document, '{job}', (document->'job') || '{"state":"interrupted","error":"Сервер перезапущен. Готовые модули сохранены."}'::jsonb)
                WHERE document->'job'->>'state' IN ('running','queued')""")

    def all(self, sql, params=()):
        with self.pool.connection() as connection:
            return connection.execute(sql, params).fetchall()

    def one(self, sql, params=()):
        with self.pool.connection() as connection:
            return connection.execute(sql, params).fetchone()

    def execute(self, sql, params=()):
        with self.pool.connection() as connection:
            return connection.execute(sql, params).rowcount

    def close(self):
        if getattr(self, "guard", None):
            self.guard.execute("SELECT pg_advisory_unlock(421572019)")
            self.pool.putconn(self.guard)
            self.guard = None
        self.pool.close()
