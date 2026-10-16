"""Create/start an isolated local PostgreSQL cluster; never touches other clusters."""
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import dotenv_values, set_key

env_path = ROOT / ".env"
settings = dotenv_values(env_path)
if settings.get("DATABASE_URL") and not settings.get("EDENTICA_LOCAL_POSTGRES"):
    raise SystemExit("DATABASE_URL уже настроен. Локальная БД не создана; используется ваша конфигурация.")
binary = Path(os.getenv("POSTGRES_BIN") or r"C:\Program Files\PostgreSQL\18\bin")
if not (binary / "pg_ctl.exe").exists():
    found = shutil.which("pg_ctl")
    if not found:
        raise SystemExit("Установите PostgreSQL или задайте POSTGRES_BIN")
    binary = Path(found).parent
suffix = ".exe" if os.name == "nt" else ""
cluster = ROOT / "data/postgres"
port = settings.get("EDENTICA_POSTGRES_PORT") or "55432"
def run(name, *args, **kwargs):
    return subprocess.run([str(binary / (name + suffix)), *map(str, args)], check=True, **kwargs)

if not cluster.exists():
    cluster.parent.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(32)
    password_file = ROOT / "data/.pg-password-temp"
    password_file.write_text(password, encoding="utf-8")
    try:
        run("initdb", "-D", cluster, "-U", "edentica", "--pwfile", password_file,
            "--auth-host=scram-sha-256", "--auth-local=scram-sha-256", "--encoding=UTF8", "--locale=C")
    finally:
        password_file.unlink(missing_ok=True)
    with (cluster / "postgresql.conf").open("a", encoding="utf-8") as stream:
        stream.write(f"\nlisten_addresses = '127.0.0.1'\nport = {port}\n")
    set_key(env_path, "DATABASE_URL", f"postgresql://edentica:{password}@127.0.0.1:{port}/edentica")
    set_key(env_path, "EDENTICA_LOCAL_POSTGRES", "1")
    set_key(env_path, "EDENTICA_POSTGRES_PORT", port)
elif not settings.get("DATABASE_URL"):
    raise SystemExit("Кластер уже существует, но DATABASE_URL отсутствует. Восстановите настройки .env.")

running = subprocess.run([str(binary / ("pg_ctl" + suffix)), "-D", str(cluster), "status"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
if not running:
    run("pg_ctl", "-D", cluster, "-l", ROOT / "data/postgres.log", "-w", "start")
import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
url = dotenv_values(env_path)["DATABASE_URL"]
config = conninfo_to_dict(url)
database_name = config.pop("dbname")
with psycopg.connect(make_conninfo(**config, dbname="postgres"), autocommit=True) as connection:
    if not connection.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database_name,)).fetchone():
        from psycopg import sql
        connection.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8' TEMPLATE template0").format(sql.Identifier(database_name)))
print(f"PostgreSQL готов: 127.0.0.1:{port}; база edentica. Пароль сохранён только в .env.")
