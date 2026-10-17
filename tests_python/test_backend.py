import asyncio
import base64
import copy
from io import BytesIO
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import time
from uuid import uuid4
from zipfile import ZipFile

from fastapi.testclient import TestClient
import psycopg
from psycopg.types.json import Jsonb
import pytest

from backend.app import create_app, check_password, hash_password
from backend.database import ROOT
from backend.rules import Rules

HEADERS = {"X-Edentica": "1"}


def register(client):
    email = f"qa-{uuid4().hex}@example.test"
    response = client.post("/api/auth/register", headers=HEADERS,
                           json={"name": "Методист", "email": email, "password": "password-test-long"})
    assert response.status_code == 200, response.text
    return response.json(), email


def agent(client, action, **data):
    return client.post("/api/agent", headers=HEADERS, json={"action": action, **data})


def wait(client, id):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        response = agent(client, "get", id=id)
        assert response.status_code == 200, response.text
        p = response.json()
        if p.get("job", {}).get("state") not in ("running", "queued"):
            return p
        time.sleep(.05)
    raise AssertionError("Agent job timeout")


def test_authentication_security_and_static(client):
    assert client.get("/api/health").json()["database"] == "postgresql"
    assert "<title>Эдентика</title>" in client.get("/").text
    for asset in ("favicon.svg", "favicon.png", "favicon.ico", "brand.svg", "brand.png",
                  "program-studio.js", "program-studio.css", "program-editor.js"):
        assert client.get("/" + asset).status_code == 200
    assert agent(client, "list").status_code == 401
    account, email = register(client)
    assert client.get("/api/me").json()["user"]["id"] == account["id"]
    assert "HttpOnly" in str(client.cookies) or client.cookies.get("session")
    assert client.post("/api/agent", json={"action": "list"}).status_code == 403
    assert client.post("/api/agent", headers={**HEADERS, "Origin": "https://external.test"}, json={"action": "list"}).status_code == 403
    assert client.post("/api/agent", headers=HEADERS, content="[]").status_code == 400
    assert client.post("/api/agent", headers=HEADERS, content="broken").status_code == 400
    assert client.post("/api/agent", headers=HEADERS, content="a" * 200001).status_code == 413
    assert client.get("/api/me", headers={"Host": "evil.test"}).status_code == 403
    assert client.get("/api/ai/status").status_code == 410
    assert client.get("/.env").status_code == 404
    assert client.post("/api/auth/logout", headers=HEADERS, json={}).status_code == 200
    assert client.get("/api/me").json()["user"] is None
    assert client.post("/api/auth/login", headers=HEADERS, json={"email": email, "password": "wrong-password"}).status_code == 401
    assert client.post("/api/auth/login", headers=HEADERS, json={"email": email, "password": "password-test-long"}).status_code == 200


def test_passwords_compatible_with_node_scrypt():
    result = subprocess.check_output(["node", "--input-type=module", "-e",
        "import {scryptSync} from 'node:crypto';console.log('abcd:'+scryptSync('password-test-long','abcd',64).toString('hex'))"], text=True).strip()
    assert check_password("password-test-long", result)
    assert not check_password("bad-password", result)
    assert not check_password("x", "invalid")


def test_materials_ownership_demo_exports_and_revision(client):
    account, _ = register(client)
    uploaded = client.post("/api/materials", headers=HEADERS,
                           json={"name": "reference.txt", "data": base64.b64encode("Референс программы".encode()).decode()})
    assert uploaded.status_code == 201, uploaded.text
    ref = uploaded.json()["id"]
    assert client.get("/api/materials/" + ref).json()["text"] == "Референс программы"
    assert len(client.get("/api/materials").json()) == 1
    p = agent(client, "demo").json()
    assert agent(client, "export", id=p["id"], format="docx").status_code == 422
    approved = agent(client, "approve", id=p["id"], expectedRevision=p["revision"], confirm=True)
    assert approved.status_code == 200, approved.text
    report = agent(client, "validate", id=p["id"]).json()
    assert report["passed"], report
    gift = agent(client, "export", id=p["id"], format="gift")
    assert gift.status_code == 200 and "::" in gift.text
    docx = agent(client, "export", id=p["id"], format="docx")
    assert docx.status_code == 200, docx.text
    with ZipFile(BytesIO(docx.content)) as archive:
        document = archive.read("word/document.xml").decode()
        assert "Первые шаги в Python" in document
    from backend.exports import pptx_available
    if pptx_available():
        slides = agent(client, "export", id=p["id"], format="pptx", moduleId="М1")
        assert slides.status_code == 200, slides.text[:300]
        with ZipFile(BytesIO(slides.content)) as archive:
            assert "ppt/presentation.xml" in archive.namelist()
            assert any(name.startswith("ppt/notesSlides/notesSlide") for name in archive.namelist())
    exported = agent(client, "export", id=p["id"], format="json").json()
    assert exported["report"]["passed"]
    skeleton = copy.deepcopy(p["skeleton"])
    skeleton["goal"] += " Дополнительная проверка."
    assert agent(client, "edit_skeleton", id=p["id"], expectedRevision=0, skeleton=skeleton).status_code == 409
    edited = agent(client, "edit_skeleton", id=p["id"], expectedRevision=p["revision"], skeleton=skeleton).json()
    assert edited["approval"] is None and edited["materials"] == {}
    assert agent(client, "export", id=p["id"], format="gift").status_code == 422
    register(client)  # a second account must not see the first account's data
    assert agent(client, "get", id=p["id"]).status_code == 404
    assert client.get("/api/materials/" + ref).status_code == 404
    assert agent(client, "create", request="Курс", referenceIds=[ref]).status_code == 422


def test_real_orchestration_with_mock_provider(postgres_url):
    rules = Rules()
    fixture = asyncio.run(rules.call("demonstration"))
    sections = asyncio.run(rules.call("config"))["templateSections"]
    calls = []
    async def complete(skill, payload):
        calls.append(skill)
        if "Навык 1" in skill:
            value = {"requirements": {"type": "general", "totalHours": 16, "audience": "Школьники", "entryLevel": "Без опыта", "format": "Очно", "assessment": "Проект"},
                     "questions": [] if payload["answers"].get("level") else [{"field": "level", "question": "Какой входной уровень?"}], "notes": []}
        elif "Навык 2" in skill:
            value = copy.deepcopy(fixture["skeleton"])
        elif "Навык 3" in skill or "Навык 5" in skill:
            value = copy.deepcopy(fixture["materials"][payload["module"]["id"]])
            if payload.get("instruction"):
                value["summary"] = "Точечно обновлённое содержание"
        else:
            value = {"sections": {x: "Раздел учебной программы для школьников" for x in sections["general"]},
                     "finalAssessment": fixture["finalAssessment"], "sources": fixture["sources"]}
        return {"value": value, "usage": {"inputTokens": 100, "outputTokens": 50}, "model": "mock-only"}
    with TestClient(create_app(postgres_url, complete), base_url="http://localhost") as client:
        register(client)
        p = agent(client, "create", request="Курс Python на 16 часов").json()
        id = p["id"]
        assert agent(client, "generate", id=id).status_code == 422
        agent(client, "analyze", id=id)
        assert wait(client, id)["state"] == "clarification"
        assert agent(client, "skeleton", id=id).status_code == 422
        agent(client, "analyze", id=id, answers={"level": "Начальный"})
        assert wait(client, id)["state"] == "ready_for_skeleton"
        agent(client, "skeleton", id=id)
        p = wait(client, id)
        assert p["state"] == "skeleton_review", p.get("job")
        assert agent(client, "approve", id=id, expectedRevision=p["revision"], confirm=True).status_code == 200
        agent(client, "generate", id=id)
        p = wait(client, id)
        assert p["job"]["state"] == "completed", p["job"]
        assert p["report"]["passed"], p["report"]
        assert p["usage"]["inputTokens"] == len(calls) * 100
        untouched = copy.deepcopy(p["materials"]["М2"])
        agent(client, "revise_module", id=id, moduleId="М1", instruction="Обновите пояснение")
        p = wait(client, id)
        assert p["materials"]["М2"] == untouched
        assert p["materials"]["М1"]["summary"] == "Точечно обновлённое содержание"
        assert p["history"][-1]["materials"]["М1"]["summary"] != p["materials"]["М1"]["summary"]
        assert agent(client, "export", id=id, format="gift").status_code == 200
        source = p["sources"][0]
        assert source["verification"]["status"] == "unverified"
        assert agent(client, "verify_source", id=id, sourceId=source["id"], status="confirmed", evidence="https://docs.python.org/3/tutorial/ — проверено содержание").status_code == 200
        assert agent(client, "restore", id=id, revision=p["history"][-1]["revision"]).json()["approval"] is None


def test_cancel_persistence_and_restart(postgres_url):
    async def blocked(skill, payload):
        await asyncio.sleep(30)
    app = create_app(postgres_url, blocked)
    with TestClient(app, base_url="http://localhost") as client:
        account, email = register(client)
        p = agent(client, "create", request="Курс для проверки отмены").json()
        agent(client, "analyze", id=p["id"])
        assert agent(client, "cancel", id=p["id"]).status_code == 200
        cancelled = agent(client, "get", id=p["id"]).json()
        assert cancelled["job"]["state"] == "cancelled"
        # Simulate a previously killed worker, then check restart recovery.
        cancelled["job"]["state"] = "running"
        with psycopg.connect(postgres_url) as connection:
            connection.execute("UPDATE program_projects SET document=%s WHERE id=%s", (Jsonb(cancelled), p["id"]))
    with TestClient(create_app(postgres_url), base_url="http://localhost") as client:
        assert client.post("/api/auth/login", headers=HEADERS, json={"email": email, "password": "password-test-long"}).status_code == 200
        persisted = agent(client, "get", id=p["id"]).json()
        assert persisted["job"]["state"] == "interrupted"
        assert persisted["request"] == p["request"]


def test_sqlite_import_is_idempotent_and_preserves_passwords(postgres_url, tmp_path):
    source = tmp_path / "source.sqlite"
    id, email = str(uuid4()), f"import-{uuid4().hex}@example.test"
    with sqlite3.connect(source) as original:
        original.executescript("CREATE TABLE users(id TEXT,name TEXT,email TEXT,password TEXT,created TEXT); CREATE TABLE old_courses(id TEXT,title TEXT); CREATE TABLE program_projects(id TEXT,owner TEXT,document TEXT,updated TEXT);")
        original.execute("INSERT INTO users VALUES(?,?,?,?,?)", (id, "Импорт", email, hash_password("password-test-long"), "2026-10-15 12:00:00"))
        original.execute("INSERT INTO old_courses VALUES(?,?)", ("old", "Сохранённый старый курс"))
        rules = Rules()
        fixture = asyncio.run(rules.call("demonstration"))
        config = asyncio.run(rules.call("config"))
        imported_id = str(uuid4())
        imported = {**fixture, "id": imported_id, "owner": id, "request": "Согласованный пример", "revision": 1,
                    "state": "approved", "requirements": {}, "referenceIds": [], "demo": True, "job": None,
                    "sections": {s: "Раздел согласованной программы" for s in config["templateSections"]["general"]}}
        imported["approval"] = {"digest": asyncio.run(rules.call("digest", fixture["skeleton"])), "by": id,
                                "at": "2026-10-15T12:00:00Z", "revision": 1}
        original.execute("INSERT INTO program_projects VALUES(?,?,?,?)", (imported_id, id, json.dumps(imported, ensure_ascii=False), "2026-10-15 12:00:00"))
    spec = importlib.util.spec_from_file_location("migrate_postgres", ROOT / "scripts/migrate-postgres.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.migrate(source, postgres_url)
    module.migrate(source, postgres_url)
    with psycopg.connect(postgres_url) as connection:
        assert connection.execute("SELECT count(*) FROM users WHERE id=%s", (id,)).fetchone()[0] == 1
        assert connection.execute("SELECT record->>'title' FROM legacy_records WHERE table_name='old_courses'").fetchone()[0] == "Сохранённый старый курс"
    with TestClient(create_app(postgres_url), base_url="http://localhost") as client:
        response = client.post("/api/auth/login", headers=HEADERS, json={"email": email, "password": "password-test-long"})
        assert response.status_code == 200, response.text
        program = agent(client, "get", id=imported_id).json()
        assert program["approval"]["by"] == id
        assert program["approval"]["storageMigration"]["from"] == "sqlite"
        assert agent(client, "export", id=imported_id, format="gift").status_code == 200


def test_source_checks_do_not_fetch_arbitrary_hosts():
    from backend.programs import probe_source
    for url in ("http://127.0.0.1/", "https://metadata.google.internal/", "https://docs.python.org.evil.test/", "https://user:pass@docs.python.org/", "https://docs.python.org:444/"):
        result = asyncio.run(probe_source({"url": url}))
        assert result["access"] == "manual_review"


def test_delete_requires_confirmation_and_ownership(client):
    account, email = register(client)
    ref = client.post("/api/materials", headers=HEADERS, json={"name": "keep.txt", "data": base64.b64encode(b"Reference to keep").decode()}).json()["id"]
    p = agent(client, "create", request="Удаляемая программа", referenceIds=[ref]).json()
    other = agent(client, "create", request="Сохраняемая программа").json()
    assert agent(client, "delete", id=p["id"]).status_code == 422
    assert agent(client, "get", id=p["id"]).status_code == 200
    register(client)
    assert agent(client, "delete", id=p["id"], confirm=True).status_code == 404
    client.post("/api/auth/login", headers=HEADERS, json={"email": email, "password": "password-test-long"})
    assert agent(client, "delete", id=p["id"], confirm=True).json()["ok"]
    assert agent(client, "get", id=p["id"]).status_code == 404
    assert agent(client, "delete", id=p["id"], confirm=True).status_code == 404
    assert agent(client, "get", id=other["id"]).status_code == 200
    assert client.get("/api/materials/" + ref).status_code == 200
    assert p["id"] not in [x["id"] for x in agent(client, "list").json()]
    assert client.app.state.db.one("SELECT count(*) AS n FROM program_events WHERE project_id=%s", (p["id"],))["n"] == 0


def test_delete_cancels_running_job_without_recreating_program(postgres_url):
    async def blocked(skill, payload):
        await asyncio.sleep(30)
    app = create_app(postgres_url, blocked)
    with TestClient(app, base_url="http://localhost") as client:
        register(client)
        p = agent(client, "create", request="Удаление во время генерации").json()
        assert agent(client, "analyze", id=p["id"]).status_code == 200
        assert p["id"] in app.state.programs.jobs
        assert agent(client, "delete", id=p["id"], confirm=True).status_code == 200
        assert p["id"] not in app.state.programs.jobs
        assert agent(client, "get", id=p["id"]).status_code == 404
        assert app.state.db.one("SELECT count(*) AS n FROM program_events WHERE project_id=%s", (p["id"],))["n"] == 0


def test_cloudru_http_contract_without_real_calls(monkeypatch):
    import httpx
    from types import SimpleNamespace
    from backend import cloudru
    monkeypatch.setenv("CLOUDRU_API_KEY", "test-key-only")
    monkeypatch.setenv("CLOUDRU_MODEL", "test-model-only")
    replies = [
        {"choices": [{"message": {"content": '```json\n{"ok":true}\n```'}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 20, "completion_tokens": 8}},
        {"choices": [{"message": {"content": "{}"}, "finish_reason": "length"}]},
        {"choices": [{"message": {"content": "invalid"}, "finish_reason": "stop"}]},
    ]
    def handle(request):
        assert str(request.url) == "https://foundation-models.api.cloud.ru/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-key-only"
        assert json.loads(request.content)["model"] == "test-model-only"
        return httpx.Response(200, json=replies.pop(0))
    monkeypatch.setattr(cloudru, "httpx", SimpleNamespace(AsyncClient=lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)))
    result = asyncio.run(cloudru.complete("test instruction", {"request": "test"}))
    assert result["value"]["ok"]
    assert result["usage"] == {"inputTokens": 20, "outputTokens": 8}
    with pytest.raises(ValueError, match="обрезан"):
        asyncio.run(cloudru.complete("test", {}))
    with pytest.raises(ValueError, match="JSON"):
        asyncio.run(cloudru.complete("test", {}))


def test_hour_validation_across_program_sizes():
    rules = Rules()
    fixture = asyncio.run(rules.call("demonstration"))
    for hours in (16, 36, 72, 256, 500):
        plan = copy.deepcopy(fixture["skeleton"])
        plan.update(totalHours=hours, finalHours=2, selfStudyOnly=True,
                    modules=[{"id": "m", "title": "Стажировка", "totalHours": hours-2,
                              "topics": [{"id": "t", "title": "Самостоятельная работа", "totalHours": hours-2,
                                          "hours": {"lecture": 0, "practice": 0, "lab": 0, "self": hours-2},
                                          "competencyIds": [c["id"] for c in plan["competencies"]]}]}],
                    calendar={"weeks": 4, "sessions": [{"week": 1, "hours": hours-2, "topicIds": ["t"]}, {"week": 4, "hours": 2, "topicIds": ["final"]}]})
        assert not asyncio.run(rules.call("inspectSkeleton", plan))["errors"]
        plan["modules"][0]["topics"][0]["hours"]["practice"] = 1
        assert any(x["code"] == "internship_contact" for x in asyncio.run(rules.call("inspectSkeleton", plan))["errors"])
