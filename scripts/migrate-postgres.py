"""Transactional import: active studio tables plus a JSONB archive of all old LMS data.
The SQLite source is read only. Identical snapshots are imported once.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
from dotenv import load_dotenv
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def digest(value):
    result = subprocess.run([os.getenv("NODE_PATH") or "node", str(ROOT / "scripts/program-rules.mjs")],
                            input=json.dumps({"operation": "digest", "args": [value]}, ensure_ascii=False) + "\n",
                            capture_output=True, text=True, encoding="utf-8", check=True, timeout=15)
    return json.loads(result.stdout)["value"]


def migrate_approval(original, stored):
    # JSONB reorders object keys. Preserve valid human consent for the identical
    # skeleton while recalculating its storage-order-dependent legacy digest.
    approval = original.get("approval")
    if not approval:
        return stored
    if approval.get("digest") == digest(original.get("skeleton")):
        stored["approval"]["storageMigration"] = {"from": "sqlite", "previousDigest": approval["digest"]}
        stored["approval"]["digest"] = digest(stored.get("skeleton"))
    else:
        stored["approval"] = None
        stored["state"] = "skeleton_review"
        stored.setdefault("notes", []).append("При переносе найдено устаревшее согласование. Подтвердите текущий каркас повторно.")
    return stored


def migrate(source, target):
    source = Path(source).resolve()
    if not source.is_file():
        raise ValueError("Исходный SQLite-файл не найден")
    original = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
    original.row_factory = sqlite3.Row
    original.execute("BEGIN")
    tables = [r[0] for r in original.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    rows = {table: [dict(row) for row in original.execute('SELECT * FROM "' + table.replace('"', '""') + '"')] for table in tables}
    fingerprint = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    backup_dir = ROOT / "data/backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"before-postgres-{fingerprint[:16]}.sqlite"
    if not backup_path.exists():
        with sqlite3.connect(backup_path) as backup:
            original.backup(backup)
    original.close()
    counts = {}
    with psycopg.connect(target) as connection:
        if not connection.execute("SELECT pg_try_advisory_xact_lock(421572019)").fetchone()[0]:
            raise ValueError("Остановите Python-сервер перед переносом данных")
        connection.execute((ROOT / "backend/schema.sql").read_text(encoding="utf-8"))
        connection.execute("""CREATE TABLE IF NOT EXISTS legacy_imports(
            fingerprint TEXT PRIMARY KEY, imported_at TIMESTAMPTZ NOT NULL DEFAULT now(), counts JSONB NOT NULL);
            CREATE TABLE IF NOT EXISTS legacy_records(
            fingerprint TEXT REFERENCES legacy_imports(fingerprint), table_name TEXT NOT NULL,
            row_number INTEGER NOT NULL, record JSONB NOT NULL,
            PRIMARY KEY(fingerprint,table_name,row_number));""")
        if connection.execute("SELECT 1 FROM legacy_imports WHERE fingerprint=%s", (fingerprint,)).fetchone():
            print("Этот снимок уже перенесён; повторный импорт пропущен.")
            return
        specs = {
            "users": ("id", "name", "email", "password", "created"),
            "sessions": ("token", "user_id", "expires"),
            "user_suspensions": ("user_id", "reason"),
            "learning_materials": ("id", "user_id", "name", "kind", "size", "text", "truncated", "created"),
            "program_projects": ("id", "owner", "document", "updated"),
            "program_events": ("id", "project_id", "owner", "action", "detail", "created"),
        }
        for table, columns in specs.items():
            inserted = 0
            for row in rows.get(table, []):
                primary = columns[0]
                existing = connection.execute(sql.SQL("SELECT * FROM {} WHERE {}=%s").format(sql.Identifier(table), sql.Identifier(primary)), (row[primary],)).fetchone()
                if existing:
                    continue
                values = []
                for column in columns:
                    value = row.get(column, "" if column == "reason" else None)
                    if column in ("document", "detail"):
                        value = Jsonb(json.loads(value))
                    elif column in ("created", "updated") and not value:
                        value = datetime.now(timezone.utc)
                    values.append(value)
                connection.execute(sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                    sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, columns)),
                    sql.SQL(",").join(sql.Placeholder() for _ in columns)), values)
                if table == "program_projects":
                    stored = connection.execute("SELECT document FROM program_projects WHERE id=%s", (row[primary],)).fetchone()[0]
                    stored = migrate_approval(json.loads(row["document"]), stored)
                    connection.execute("UPDATE program_projects SET document=%s WHERE id=%s", (Jsonb(stored), row[primary]))
                inserted += 1
            counts[table] = {"source": len(rows.get(table, [])), "inserted": inserted}
        connection.execute("INSERT INTO legacy_imports(fingerprint,counts) VALUES(%s,%s)", (fingerprint, Jsonb(counts)))
        for table, records in rows.items():
            for index, record in enumerate(records):
                connection.execute("INSERT INTO legacy_records VALUES(%s,%s,%s,%s)", (fingerprint, table, index, Jsonb(record)))
    print(json.dumps({"imported": counts, "archivedTables": len(tables), "backup": str(backup_path)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(ROOT / "data/edentica.sqlite"))
    args = parser.parse_args()
    if not os.getenv("DATABASE_URL"):
        raise SystemExit("Настройте DATABASE_URL")
    migrate(args.source, os.environ["DATABASE_URL"])
