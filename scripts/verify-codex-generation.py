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

ROOT = Path.cwd() if __file__ == '<stdin>' else Path(__file__).resolve().parent.parent
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
parser.add_argument("--provider", choices=['codex','gateway'], default='codex')
parser.add_argument('--workflow',action='store_true')
parser.add_argument('--case',choices=['python16','bank72'],default='python16')
args = parser.parse_args()
if args.provider=='codex':
    assert os.getenv("EDENTICA_MODE") == "local" and os.getenv("LLM_PROVIDER") == "codex"
else:
    assert os.getenv('LLM_BASE_URL') and os.getenv('LLM_API_KEY')
    # Applies only inside this isolated verification process, never to the server.
    os.environ['SYSTEM_LLM_SHARED_ACCESS']='1'
url = urlsplit(os.environ["DATABASE_URL"])
name = "edentica_codexcheck_" + uuid4().hex
admin_url = urlunsplit((url.scheme, url.netloc, "/postgres", url.query, url.fragment))
test_url = urlunsplit((url.scheme, url.netloc, "/" + name, url.query, url.fragment))
with psycopg.connect(admin_url, autocommit=True) as connection:
    connection.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(name)))
headers = {"X-Edentica": "1"}
started = time.monotonic()
report = {"startedAt": datetime.now(timezone.utc).isoformat(), "provider": args.provider, "full": args.full,'case':args.case}
output = ROOT / ("output/codex-real-check" if args.provider=='codex' else "data/gateway-real-check"+('-bank72' if args.case=='bank72' else ''))
output.mkdir(parents=True,exist_ok=True)
latest=None
try:
    with TestClient(create_app(test_url), base_url="https://localhost") as client:
        response = client.post("/api/auth/register", headers=headers, json={"name": "Проверка генерации", "email": "generation@example.test", "password": "temporary-test-only"})
        response.raise_for_status()

        def agent(action, **data):
            response = client.post("/api/programs" if args.workflow else "/api/agent", headers=headers, json={"action": action, **data})
            response.raise_for_status()
            return response.json()

        def wait(id):
            global latest
            deadline, previous = time.monotonic() + 1200, None
            while time.monotonic() < deadline:
                p = agent("get", id=id)
                latest=p
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
        assert state["configured"] and (args.provider!='codex' or state["localTesting"]), state
        brief="Дополнительная общеразвивающая программа «Первые шаги в Python» на 16 академических часов для школьников 8–9 классов без опыта программирования. Очная форма, 4 недели, 8 занятий по 2 часа. Минимум половина часов — практика. Итоговая аттестация — защита небольшой игры на Python, 2 часа внутри общего объёма. Нужен итоговый тест на 10 вопросов с ответами, задания с критериями, планы лекций и слайды. Профстандарты не требуются."
        if args.case=='bank72':
            brief='Программа повышения квалификации «Анализ банковских данных на Python» на 72 академических часа для сотрудников банка, умеющих работать в Excel, без опыта Python. Очно-заочная форма, 6 недель. Не менее 36 часов практики. Итоговая аттестация — защита проекта анализа обезличенных транзакций, 4 часа внутри 72. Достаточно 4 модулей по 1–2 темы. Нужны 12 тестовых вопросов с ключами, задания с критериями, полные лекции и слайды. Неподтверждённые профстандарты пометь явно, номера не выдумывай.'
        p = agent("create", request=brief)
        id = p["id"]
        agent("workflow" if args.workflow else "analyze", id=id)
        p = wait(id)
        assert p["state"] in ("ready_for_skeleton","skeleton_review"), {"state": p["state"], "questions": p["questions"]}
        if p['state']=='ready_for_skeleton':
            agent("skeleton", id=id)
            p = wait(id)
        assert p["skeleton"]["totalHours"] == (72 if args.case=='bank72' else 16)
        assert p['skeleton']['type']==('dpp' if args.case=='bank72' else 'general')
        report.update(skeletonSeconds=round(time.monotonic() - started, 2), modules=len(p["skeleton"]["modules"]))
        if args.full:
            agent("approve", id=id, expectedRevision=p["revision"], confirm=True)
            agent("workflow" if args.workflow else "generate", id=id)
            p = wait(id)
            report.update(structurePassed=p["report"]["passed"], validationErrors=p["report"]["errors"],
                          coverage=len(p["report"]["coverage"]), readyModules=len(p["materials"]))
        if args.full:
            for format in ('docx','pptx','gift','json','report','zip'):
                exported=client.post('/api/programs',headers=headers,json={'action':'export','id':id,'format':format})
                exported.raise_for_status()
                assert len(exported.content)>50
                (output / ('validation-report.html' if format=='report' else 'program.'+format)).write_bytes(exported.content)
            assert p['report']['passed'],p['report']['errors']
        report.update(usage=p["usage"], seconds=round(time.monotonic() - started, 2), state=p["state"])
        (output / "program.json").write_text(json.dumps(p, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False), flush=True)
except Exception as error:
    report.update(success=False,errorType=type(error).__name__,error=str(error)[:3000],seconds=round(time.monotonic()-started,2))
    (output/'failure-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if latest:(output/'failure-program.json').write_text(json.dumps(latest,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    raise
finally:
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
