"""Produce a PostgreSQL custom-format backup without exposing credentials."""
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
from dotenv import load_dotenv
from psycopg.conninfo import conninfo_to_dict

root = Path(__file__).resolve().parent.parent
load_dotenv(root / ".env")
config = conninfo_to_dict(os.environ["DATABASE_URL"])
binary = shutil.which("pg_dump") or r"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe"
restore = str(Path(binary).with_name("pg_restore.exe" if os.name == "nt" else "pg_restore"))
target = root / "data/backups" / ("edentica-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".dump")
target.parent.mkdir(parents=True, exist_ok=True)
env = os.environ.copy()
env.update({"PG" + k: str(config[v]) for k, v in {"HOST": "host", "PORT": "port", "USER": "user", "PASSWORD": "password", "DATABASE": "dbname", "SSLMODE": "sslmode"}.items() if v in config})
subprocess.run([binary, "--format=custom", "--file", str(target)], env=env, check=True)
subprocess.run([restore, "--list", str(target)], check=True, stdout=subprocess.DEVNULL)
print("Резервная копия PostgreSQL проверена: " + str(target))
