"""Educational agent orchestration and human approval, owned by the Python API."""
import asyncio
import copy
from datetime import datetime, timezone
import json
import os
import re
from uuid import uuid4
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from psycopg.types.json import Jsonb

from . import cloudru
from .exports import export_program


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ensure(condition, message, code=422):
    if not condition:
        raise HTTPException(code, message)


def required(value, maximum=200):
    ensure(isinstance(value, str) and 0 < len(value.strip()) <= maximum
           and not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", value), "Проверьте заполнение полей")
    return value.strip()


HOSTS = {"docs.python.org", "pandas.pydata.org", "numpy.org", "scipy.org", "matplotlib.org",
         "www.postgresql.org", "www.sqlite.org", "docs.docker.com", "git-scm.com", "kubernetes.io",
         "prometheus.io", "publication.pravo.gov.ru", "pravo.gov.ru", "profstandart.rosmintrud.ru",
         "cloud.ru", "developers.sber.ru"}


async def probe_source(source):
    result = {"checkedAt": now(), "status": "unverified",
              "note": "Доступность URL не подтверждает достоверность и актуальность содержания."}
    try:
        url = urlsplit(source.get("url", ""))
        if url.scheme != "https" or url.username or url.password or url.port not in (None, 443) or url.hostname not in HOSTS:
            return {**result, "access": "manual_review"}
    except ValueError:
        return {**result, "access": "invalid_url"}
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
            response = await client.head(source["url"])
        return {**result, "httpStatus": response.status_code,
                "access": "reachable" if response.is_success else "redirect_requires_review" if response.is_redirect else "unavailable"}
    except httpx.HTTPError:
        return {**result, "access": "unavailable"}


class Programs:
    def __init__(self, db, rules, complete=None):
        self.db, self.rules = db, rules
        self.complete = complete or cloudru.complete
        self.allow_unconfigured = complete is not None
        self.jobs = {}
        self.locks = {}
        self.launch_lock = asyncio.Lock()
        self.closed = False

    async def initialize(self):
        config = await self.rules.call("config")
        self.skills, self.sections = config["skills"], config["templateSections"]

    async def query(self, method, *args):
        task = asyncio.create_task(asyncio.to_thread(getattr(self.db, method), *args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # A DB thread cannot be cancelled. Finish its write before saving the
            # cancelled job, so a delayed write cannot restore stale job state.
            await task
            raise

    async def save(self, p):
        p["updatedAt"] = now()
        await self.query("execute", "UPDATE program_projects SET document=%s, updated=now() WHERE id=%s AND owner=%s",
                         (Jsonb(copy.deepcopy(p)), p["id"], p["owner"]))

    async def event(self, p, action, detail=None):
        await self.query("execute", "INSERT INTO program_events(id,project_id,owner,action,detail) VALUES(%s,%s,%s,%s,%s)",
                         (str(uuid4()), p["id"], p["owner"], action, Jsonb(detail or {})))

    def revision(self, p):
        fields = ("revision", "skeleton", "materials", "sections", "finalAssessment", "sources", "approval")
        snapshot = copy.deepcopy({k: p.get(k) for k in fields})
        p["history"] = (p.get("history", []) + [{**snapshot, "at": now()}])[-15:]
        p["revision"] += 1

    async def load(self, id, owner):
        row = await self.query("one", "SELECT document FROM program_projects WHERE id=%s AND owner=%s", (id, owner))
        ensure(row, "Программа не найдена", 404)
        return row["document"]

    def idle(self, p):
        ensure(p["id"] not in self.jobs, "Дождитесь завершения текущей задачи или отмените её")

    async def references(self, p):
        rows = await self.query("all", "SELECT name,text,truncated FROM learning_materials WHERE id=ANY(%s) AND user_id=%s",
                                (p["referenceIds"], p["owner"]))
        return [{**r, "text": r["text"][:22000], "trust": "untrusted-reference"} for r in rows]

    async def call(self, p, skill, payload):
        result = await self.complete(self.skills[skill], payload)
        usage = p["usage"]
        for key in ("inputTokens", "outputTokens"):
            usage[key] += result.get("usage", {}).get(key, 0)
        usage["calls"] += 1
        usage["model"] = result.get("model") or cloudru.status()["model"]
        incoming, outgoing = os.getenv("CLOUDRU_INPUT_RUB_PER_MILLION"), os.getenv("CLOUDRU_OUTPUT_RUB_PER_MILLION")
        usage["estimatedRubles"] = (usage["inputTokens"] * float(incoming) + usage["outputTokens"] * float(outgoing)) / 1e6 if incoming and outgoing else None
        return result["value"]

    async def launch(self, p, kind, work):
        async with self.launch_lock:
            return await self._launch(p, kind, work)

    async def _launch(self, p, kind, work):
        self.idle(p)
        ensure(len(self.jobs) < 2, "Сейчас выполняются две задачи. Повторите после завершения.", 429)
        p["job"] = {"id": str(uuid4()), "kind": kind, "state": "running", "step": "Подготовка",
                    "completed": 0, "total": 1, "startedAt": now()}
        await self.save(p)
        await self.event(p, "job_started", {"kind": kind})

        async def run():
            try:
                async with asyncio.timeout(175 if kind == "skeleton" else 1180):
                    await work(p)
                p["job"]["state"] = "completed"
                p["job"]["completed"] = p["job"]["total"]
                await self.event(p, "job_completed", {"kind": kind})
            except asyncio.CancelledError:
                p["job"].update(state="cancelled", error="Задача отменена. Готовые модули сохранены.")
            except Exception as error:
                message = error.detail if isinstance(error, HTTPException) else str(error)
                p["job"].update(state="failed", error=(message or "Превышено время выполнения задачи")[:500])
                await self.event(p, "job_failed", {"kind": kind, "error": p["job"]["error"]})
            finally:
                if p["state"] == "generating":
                    p["state"] = "needs_revision"
                p["job"]["finishedAt"] = now()
                p["job"]["elapsedSeconds"] = round((datetime.now(timezone.utc) - datetime.fromisoformat(p["job"]["startedAt"])).total_seconds())
                try:
                    await self.save(p)
                finally:
                    self.jobs.pop(p["id"], None)
        self.jobs[p["id"]] = asyncio.create_task(run())
        return copy.deepcopy(p)

    def sources(self, p, sources):
        for source in sources or []:
            if not isinstance(source, dict) or not isinstance(source.get("title"), str) or not source["title"].strip():
                continue
            if not any(x["title"] == source["title"] or (x.get("url") and x["url"] == source.get("url")) for x in p["sources"]):
                p["sources"].append({"id": str(uuid4()), "title": source["title"][:2000],
                                     "url": str(source.get("url") or "")[:3000], "kind": source.get("kind", "literature"),
                                     "verification": {"status": "unverified"}})

    async def action(self, action, body, user):
        owner = user["id"]
        if action == "status":
            from .exports import pptx_available
            return {**cloudru.status(), "pptx": pptx_available(), "skills": list(self.skills),
                    "humanApprovalRequired": True, "foreignProvidersEnabled": False}
        if action == "list":
            rows = await self.query("all", "SELECT document FROM program_projects WHERE owner=%s ORDER BY updated DESC", (owner,))
            return [{"id": p["id"], "title": p.get("skeleton", {}).get("title") or p["request"][:90],
                     **{k: p.get(k) for k in ("state", "revision", "updatedAt", "demo", "job")}}
                    for row in rows for p in [row["document"]]]
        if action in ("create", "demo"):
            return await self.create(action, body, owner)
        id = required(body.get("id"), 80)
        # Serialize read-modify-write actions within this scheduler. Polling is also
        # serialized, so it never observes a half-applied user edit.
        async with self.locks.setdefault(id, asyncio.Lock()):
            p = await self.load(id, owner)
            if action == "get":
                events = await self.query("all", "SELECT action,detail,created FROM program_events WHERE project_id=%s AND owner=%s ORDER BY sequence DESC LIMIT 30", (id, owner))
                for event in events:
                    event["detail"] = json.dumps(event["detail"], ensure_ascii=False)
                return {**p, "report": await self.rules.call("inspectProgram", p) if p.get("skeleton") else None, "events": events}
            if action == "cancel":
                task = self.jobs.get(id)
                ensure(task, "Активной задачи нет")
                task.cancel()
                await task
                return {"ok": True}
            self.idle(p)
            if action in ("analyze", "skeleton"):
                ensure(not p["demo"], "Демо не вызывает модель. Создайте новую программу.")
                ensure(self.allow_unconfigured or cloudru.status()["configured"], "Настройте CLOUDRU_API_KEY и CLOUDRU_MODEL в .env", 503)
                if action == "analyze":
                    ensure(not p.get("approval"), "После согласования редактируйте каркас с новым утверждением")
                    answers = body.get("answers", {})
                    ensure(isinstance(answers, dict) and len(json.dumps(answers)) < 12000, "Проверьте ответы")
                    p["answers"] = {**p.get("answers", {}), **answers}
                    return await self.launch(p, "intake", self.analyze)
                ensure(p["state"] in ("ready_for_skeleton", "skeleton_review"), "Сначала уточните требования")
                return await self.launch(p, "skeleton", self.skeleton)
            if action == "edit_skeleton":
                ensure(body.get("expectedRevision") == p["revision"], "Версия изменилась. Обновите программу.", 409)
                report = await self.rules.call("inspectSkeleton", body.get("skeleton"), p["requirements"])
                ensure(not report["errors"], "; ".join(x["message"] for x in report["errors"]))
                old, new, kept = p.get("skeleton", {}), body["skeleton"], {}
                fields = ("type", "goal", "audience", "entryLevel", "format", "assessment", "selfStudyOnly")
                if all(old.get(k) == new.get(k) for k in fields):
                    for module in new["modules"]:
                        ids = {x for topic in module["topics"] for x in topic["competencyIds"]}
                        before = next((m for m in old.get("modules", []) if m["id"] == module["id"]), None)
                        if before == module and [c for c in old["competencies"] if c["id"] in ids] == [c for c in new["competencies"] if c["id"] in ids] and module["id"] in p["materials"]:
                            kept[module["id"]] = p["materials"][module["id"]]
                self.revision(p)
                p.update(skeleton=new, materials=kept, sections={}, finalAssessment=None, approval=None, state="skeleton_review")
                await self.save(p)
                await self.event(p, "skeleton_edited", {"preservedModules": list(kept)})
                return p
            if action == "approve":
                ensure(p.get("skeleton"), "Нет каркаса")
                ensure(body.get("expectedRevision") == p["revision"], "Версия изменилась. Обновите программу.", 409)
                ensure(body.get("confirm") is True, "Подтвердите цель, компетенции и часы")
                report = await self.rules.call("inspectSkeleton", p["skeleton"], p["requirements"])
                ensure(not report["errors"], "; ".join(x["message"] for x in report["errors"]))
                p["approval"] = {"by": owner, "at": now(), "digest": await self.rules.call("digest", p["skeleton"]), "revision": p["revision"]}
                p["state"] = "approved"
                await self.save(p)
                await self.event(p, "skeleton_approved", p["approval"])
                return p
            if action in ("generate", "revise_module"):
                await self.approved(p)
                ensure(not p["demo"], "Демо не вызывает модель")
                ensure(self.allow_unconfigured or cloudru.status()["configured"], "Cloud.ru не настроен", 503)
                target = next((m for m in p["skeleton"]["modules"] if m["id"] == body.get("moduleId")), None) if action == "revise_module" else None
                if action == "revise_module":
                    ensure(target and target["id"] in p["materials"], "Модуль не найден или ещё не создан")
                    required(body.get("instruction"), 6000)
                return await self.launch(p, action, lambda p: self.generate(p, target, body.get("instruction")))
            if action == "validate":
                return await self.rules.call("inspectProgram", p)
            if action == "check_sources":
                return await self.launch(p, "sources", self.check_sources)
            if action == "verify_source":
                source = next((x for x in p["sources"] if x["id"] == body.get("sourceId")), None)
                ensure(source, "Источник не найден")
                ensure(body.get("status") in ("confirmed", "rejected"), "Выберите статус")
                evidence = required(body.get("evidence"), 4000)
                ensure(evidence.startswith("https://"), "Укажите HTTPS ссылку и сведения о проверке")
                source["verification"] = {"status": body["status"], "evidence": evidence, "by": owner, "at": now(), "method": "human_review"}
                await self.save(p)
                await self.event(p, "source_reviewed", {"sourceId": source["id"], "status": body["status"]})
                return p
            if action == "restore":
                snapshot = next((x for x in p["history"] if x["revision"] == body.get("revision")), None)
                ensure(snapshot, "Версия не найдена")
                self.revision(p)
                for k in ("skeleton", "materials", "sections", "finalAssessment", "sources"):
                    p[k] = copy.deepcopy(snapshot.get(k))
                p.update(approval=None, state="skeleton_review")
                await self.save(p)
                await self.event(p, "restored", {"revision": body["revision"]})
                return p
            if action == "export":
                ensure(p.get("skeleton"), "Нет каркаса для выгрузки")
                report = await self.rules.call("inspectProgram", p)
                if body.get("format") != "json":
                    await self.approved(p)
                    ensure(report["passed"], "Исправьте ошибки автопроверки перед выгрузкой")
                response = await export_program({**p, "report": report, "templateSections": self.sections[p["skeleton"]["type"]]}, body.get("format"), body.get("moduleId"))
                await self.event(p, "export", {"format": body["format"]})
                return response
            raise HTTPException(422, "Неизвестная команда агента")

    async def create(self, action, body, owner):
        # Serialize the per-user quota and insertion in a PostgreSQL transaction.
        references = body.get("referenceIds", [])
        ensure(isinstance(references, list) and len(references) <= 5 and all(isinstance(x, str) for x in references), "Добавьте не более пяти референсов")
        request = "Демонстрационный пример Python для школьников" if action == "demo" else required(body.get("request"), 20000)
        p = {"id": str(uuid4()), "owner": owner, "request": request, "referenceIds": references,
             "state": "brief", "revision": 1, "requirements": {}, "questions": [], "notes": [],
             "materials": {}, "sections": {}, "sources": [], "history": [], "job": None, "approval": None,
             "usage": {"inputTokens": 0, "outputTokens": 0, "calls": 0, "estimatedRubles": None},
             "createdAt": now(), "updatedAt": now(), "demo": action == "demo"}
        if p["demo"]:
            p.update(await self.rules.call("demonstration"))
            p.update(state="skeleton_review", notes=["Это подготовленный пример для проверки интерфейса. Он не сгенерирован моделью."],
                     sections={title: f"Демонстрационное заполнение раздела «{title}». Для реальной программы используйте Cloud.ru и экспертную проверку." for title in self.sections["general"]})
        def insert():
            with self.db.pool.connection() as connection:
                connection.execute("SELECT id FROM users WHERE id=%s FOR UPDATE", (owner,))
                ensure(connection.execute("SELECT count(*) AS n FROM program_projects WHERE owner=%s", (owner,)).fetchone()["n"] < 100, "Лимит: 100 программ")
                for id in references:
                    ensure(connection.execute("SELECT id FROM learning_materials WHERE id=%s AND user_id=%s", (id, owner)).fetchone(), "Референс недоступен")
                connection.execute("INSERT INTO program_projects(id,owner,document) VALUES(%s,%s,%s)", (p["id"], owner, Jsonb(p)))
        await asyncio.to_thread(insert)
        await self.event(p, "created", {"demo": p["demo"]})
        return p

    async def approved(self, p):
        ensure(p.get("skeleton") and (p.get("approval") or {}).get("digest") == await self.rules.call("digest", p.get("skeleton")), "Методист должен утвердить текущую цель, компетенции и часы")

    async def analyze(self, p):
        p["job"]["step"] = "Уточнение требований"
        data = await self.call(p, "intake", {"request": p["request"], "answers": p.get("answers", {}), "references": await self.references(p)})
        ensure(isinstance(data.get("requirements"), dict) and isinstance(data.get("questions"), list) and len(data["questions"]) <= 5, "Некорректный разбор запроса")
        for question in data["questions"]:
            required(question.get("field"), 80)
            required(question.get("question"), 2000)
        p.update(requirements=data["requirements"], questions=data["questions"], notes=data.get("notes", []))
        count = re.search(r"(\d{1,3})\s+вопрос", p["request"], re.I)
        if count:
            p["requirements"]["testQuestionCount"] = int(count[1])
        needed = {"type": "Какой тип программы?", "totalHours": "Какой объём в академических часах?", "audience": "Для кого программа?",
                  "entryLevel": "Что слушатели уже знают?", "format": "Какая форма обучения?", "assessment": "Как проходит итоговая аттестация?"}
        missing = [k for k in needed if not p["requirements"].get(k)]
        for field in missing:
            if len(p["questions"]) < 5 and not any(q["field"] == field for q in p["questions"]):
                p["questions"].append({"field": field, "question": needed[field]})
        p["state"] = "clarification" if missing or p["questions"] else "ready_for_skeleton"
        await self.save(p)

    async def skeleton(self, p):
        p["job"]["step"] = "Карта компетенций и часы"
        candidate, issues = None, None
        for _ in range(2):
            candidate = await self.call(p, "skeleton", {"request": p["request"], "requirements": p["requirements"], "references": await self.references(p), "previous": candidate, "validationErrors": issues})
            issues = (await self.rules.call("inspectSkeleton", candidate, p["requirements"]))["errors"]
            if not issues:
                break
        ensure(not issues, "Каркас не прошёл проверку: " + "; ".join(x["message"] for x in issues[:3]))
        self.revision(p)
        p.update(skeleton=candidate, materials={}, sections={}, finalAssessment=None, approval=None, state="skeleton_review")
        await self.save(p)

    async def generate(self, p, target, instruction):
        modules = [target] if target else p["skeleton"]["modules"]
        p["job"]["total"] = 1 if target else len(modules) + 1
        p["state"] = "generating"
        for index, module in enumerate(modules):
            p["job"].update(step="Материалы: " + module["title"], completed=index)
            await self.save(p)
            if not target and p["materials"].get(module["id"]) and not await self.rules.call("inspectModule", p["materials"][module["id"]], module, p["skeleton"]):
                continue
            candidate, issues = None, None
            all_modules = p["skeleton"]["modules"]
            count = p["requirements"].get("testQuestionCount")
            quota = count // len(all_modules) + (all_modules.index(module) < count % len(all_modules)) if count else None
            for _ in range(2):
                candidate = await self.call(p, "revise" if target else "module", {
                    "request": p["request"], "requirements": p["requirements"], "skeleton": p["skeleton"], "module": module,
                    "questionQuota": quota, "referenceExcerpts": await self.references(p),
                    "previous": p["materials"].get(module["id"]) if target else candidate,
                    "instruction": instruction, "validationErrors": issues})
                issues = await self.rules.call("inspectModule", candidate, module, p["skeleton"])
                if not issues:
                    break
            ensure(not issues, "Модуль не прошёл проверку: " + "; ".join(x["message"] for x in issues[:3]))
            if target:
                self.revision(p)
            p["materials"][module["id"]] = candidate
            self.sources(p, candidate.get("sources"))
            await self.save(p)
        if not target:
            p["job"]["step"] = "Разделы шаблона и итоговая аттестация"
            await self.save(p)
            data = await self.call(p, "sections", {"skeleton": p["skeleton"], "sectionTitles": self.sections[p["skeleton"]["type"]], "requirements": p["requirements"], "knownSources": p["sources"]})
            ensure(data.get("sections") and data.get("finalAssessment"), "Модель не заполнила разделы")
            p.update(sections=data["sections"], finalAssessment=data["finalAssessment"])
            self.sources(p, data.get("sources"))
        p["state"] = "draft_ready" if (await self.rules.call("inspectProgram", p))["passed"] else "needs_revision"
        await self.save(p)

    async def check_sources(self, p):
        p["job"]["total"] = len(p["sources"])
        for index, source in enumerate(p["sources"]):
            p["job"].update(step="Проверка URL: " + source["title"], completed=index)
            source["accessCheck"] = await probe_source(source)
            await self.save(p)

    async def close(self):
        self.closed = True
        tasks = list(self.jobs.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
