"""Opt-in real model smoke check. Uses subscription limits and a disposable DB."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
import psycopg
from psycopg import sql
from fastapi.testclient import TestClient
from backend.app import create_app

parser = argparse.ArgumentParser()
parser.add_argument("--full", action="store_true", help="Also generate all module materials and sections")
args = parser.parse_args()
assert os.getenv("EDENTICA_MODE") == "local" and os.getenv("LLM_PROVIDER") == "codex"
url = urlsplit(os.environ["DATABASE_URL"])
name = "edentica_codexcheck_" + uuid4().hex
admin_url = urlunsplit((url.scheme, url.netloc, "/postgres", url.query, url.fragment))
test_url = urlunsplit((url.scheme, url.netloc, "/" + name, url.query, url.fragment))
with psycopg.connect(admin_url, autocommit=True) as connection:
    connection.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(name)))
headers = {"X-Edentica": "1"}
started = time.monotonic()
report = {"startedAt": datetime.now(timezone.utc).isoformat(), "provider": "codex", "full": args.full}
try:
    with TestClient(create_app(test_url), base_url="http://localhost") as client:
        response = client.post("/api/auth/register", headers=headers, json={"name": "Проверка генерации", "email": "generation@example.test", "password": "temporary-test-only"})
        response.raise_for_status()

        def agent(action, **data):
            response = client.post("/api/agent", headers=headers, json={"action": action, **data})
            response.raise_for_status()
            return response.json()

        def wait(id):
            deadline, previous = time.monotonic() + 1200, None
            while time.monotonic() < deadline:
                p = agent("get", id=id)
                job = p.get("job") or {}
                step = (job.get("state"), job.get("step"))
                if step != previous:
                    print({"state": step[0], "step": step[1]}, flush=True)
                    previous = step
                if job.get("state") != "running":
                    assert job.get("state") == "completed", job
                    return p
                time.sleep(1)
            raise TimeoutError("Время проверки истекло")

        state = agent("status")
        assert state["configured"] and state["localTesting"], state
        p = agent("create", request="Дополнительная общеразвивающая программа «Первые шаги в Python» на 16 академических часов для школьников 8–9 классов без опыта программирования. Очная форма, 4 недели, 8 занятий по 2 часа. Минимум половина часов — практика. Итоговая аттестация — защита небольшой игры на Python, 2 часа внутри общего объёма. Нужен итоговый тест на 10 вопросов с ответами, задания с критериями, планы лекций и слайды. Профстандарты не требуются.")
        id = p["id"]
        agent("analyze", id=id)
        p = wait(id)
        assert p["state"] == "ready_for_skeleton", {"state": p["state"], "questions": p["questions"]}
        agent("skeleton", id=id)
        p = wait(id)
        assert p["skeleton"]["totalHours"] == 16
        report.update(skeletonSeconds=round(time.monotonic() - started, 2), modules=len(p["skeleton"]["modules"]))
        if args.full:
            agent("approve", id=id, expectedRevision=p["revision"], confirm=True)
            agent("generate", id=id)
            p = wait(id)
            report.update(structurePassed=p["report"]["passed"], validationErrors=p["report"]["errors"],
                          coverage=len(p["report"]["coverage"]), readyModules=len(p["materials"]))
        report.update(usage=p["usage"], seconds=round(time.monotonic() - started, 2), state=p["state"])
        output = ROOT / "output/codex-real-check"
        output.mkdir(parents=True, exist_ok=True)
        (output / "program.json").write_text(json.dumps(p, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False), flush=True)
finally:
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
