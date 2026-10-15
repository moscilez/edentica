"""Read-only deployment checks, printing counts and health rather than user data."""
import asyncio
from pathlib import Path
import os
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
import httpx
import psycopg
from backend.rules import Rules

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
    version = connection.execute("SHOW server_version").fetchone()[0]
    rows = connection.execute("SELECT document FROM program_projects").fetchall()
    invalid = 0
    approved = 0
    for (p,) in rows:
        if p.get("approval"):
            approved += 1
            invalid += p["approval"]["digest"] != asyncio.run(Rules().call("digest", p.get("skeleton")))
    print({"postgresql": version, "programs": len(rows), "approved": approved, "invalidApprovalDigests": invalid})
    assert invalid == 0, "Найдены согласования с неверной контрольной суммой"
response = httpx.get("http://127.0.0.1:3000/api/health", timeout=5)
response.raise_for_status()
health = response.json()
assert health["backend"] == "python" and health["database"] == "postgresql"
print(health)
