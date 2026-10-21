"""Educational agent orchestration and human approval, owned by the Python API."""
import asyncio
import copy
import hashlib
from datetime import datetime, timezone
import json
import os
import re
import weakref
from uuid import uuid4
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from psycopg.types.json import Jsonb

from . import cloudru
from .codex_provider import CodexProvider
from .exports import export_program
from .models import Models
from .config import Settings
from .contracts import Intake,Requirements,Lecture,LessonAssessment,Seminar,TestQuestion,Interview
from .planning import build_skeleton,explicit_requirements,merge_requirements,schedule_question
from .canonical import canonicalize_sections,normalize_criteria
from pydantic import ValidationError
from .observability import logger


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

CORE_QUESTIONS={"type":"Какой тип программы?","totalHours":"Какой объём в академических часах?",
    "audience":"Для кого программа?","entryLevel":"Что слушатели уже знают?",
    "format":"Какая форма обучения?","assessment":"Как проходит итоговая аттестация?"}


def ensure(condition, message, code=422):
    if not condition:
        raise HTTPException(code, message)


def required(value, maximum=200):
    ensure(isinstance(value, str) and 0 < len(value.strip()) <= maximum
           and not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", value), "Проверьте заполнение полей")
    return value.strip()


def bind_lesson_item(value,topic,kind,index=1):
    """Foreign keys belong to the requested lesson scope, not model arithmetic.

    This records structural links, never asserts semantic/expert confirmation.
    Preserve any valid subset of requested outcomes provided by the model.
    """
    if not isinstance(value,dict):return value
    result={**value,'topicId':topic['id'],'bindingMethod':'requested_lesson_scope'}
    result['id']=f'{topic["id"]}-{kind}-{index}'
    if 'criteria' in result:result['criteria']=normalize_criteria(result['criteria'])
    ids=result.get('competencyIds')
    if not isinstance(ids,list) or not ids or any(x not in topic['competencyIds'] for x in ids):result['competencyIds']=list(topic['competencyIds'])
    return result


def intake_issues(value):
    if not isinstance(value, dict):
        return ['Ответ должен быть JSON-объектом']
    issues=[]
    if not isinstance(value.get('requirements'),dict):
        issues.append('requirements должен быть объектом')
    else:
        # Omitted optional values and null are equivalent at the model boundary.
        # Explicit user constraints are merged afterwards and are never discarded.
        for key in list(value['requirements']):
            if value['requirements'][key] is None and key in Requirements.model_fields and not Requirements.model_fields[key].is_required():
                value['requirements'].pop(key)
        kind=value['requirements'].get('type')
        if isinstance(kind,str) and kind not in ('general','dpp'):
            if re.search(r'повышени[ея]\s+квалификаци',kind,re.I):value['requirements']['type']='dpp'
            elif re.search(r'общеразвивающ|общеобразовательн',kind,re.I):value['requirements']['type']='general'
    if isinstance(value.get('questions'),list) and len(value['questions'])>5:value['questions']=value['questions'][:5]
    questions=value.get('questions')
    if not isinstance(questions,list) or len(questions)>5:
        issues.append('questions должен быть массивом не более пяти объектов')
    elif any(not isinstance(q,dict) or any(not isinstance(q.get(k),str) or not q[k].strip() or len(q[k])>limit for k,limit in (('field',80),('question',2000))) for q in questions):
        issues.append('Каждый элемент questions — объект {field:строка,question:строка}, а не строка')
    if not isinstance(value.get('notes',[]),list) or any(not isinstance(n,str) for n in value.get('notes',[])):
        issues.append('notes должен быть массивом строк')
    if not issues:
        try:Intake.model_validate(value)
        except ValidationError as error:issues.extend('.'.join(map(str,x['loc']))+': '+x['msg'] for x in error.errors(include_input=False))
    return issues


HOSTS = {"docs.python.org", "pandas.pydata.org", "numpy.org", "scipy.org", "matplotlib.org",
         "www.postgresql.org", "www.sqlite.org", "docs.docker.com", "git-scm.com", "kubernetes.io",
         "prometheus.io", "publication.pravo.gov.ru", "pravo.gov.ru", "profstandart.rosmintrud.ru",
         "cloud.ru", "developers.sber.ru","mintrud.gov.ru","minjust.gov.ru","mchs.gov.ru","apkit.ru",
         "docs.scipy.org","docs.kernel.org","docs.gitlab.com","opentofu.org","owasp.org"}


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
        from .net import public_request
        code,_,_=await public_request('HEAD',source['url'],timeout=8,limit=10000)
        return {**result, "httpStatus": code,
                "access": "reachable" if 200<=code<300 else "redirect_requires_review" if 300<=code<400 else "unavailable"}
    except (httpx.HTTPError,ValueError,TimeoutError):
        return {**result, "access": "unavailable"}


class Programs:
    def __init__(self, db, rules, complete=None):
        self.db, self.rules = db, rules
        provider = os.getenv("LLM_PROVIDER", "cloudru").lower()
        if provider not in ("cloudru", "codex"):
            raise ValueError("LLM_PROVIDER должен быть cloudru или codex")
        if provider == "codex" and os.getenv("EDENTICA_MODE") != "local":
            raise ValueError("Codex разрешён только при EDENTICA_MODE=local. Для хакатона используйте cloudru.")
        if provider == "codex" and (os.getenv("HOST") or "127.0.0.1") not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("Локальный Codex-провайдер разрешён только на loopback HOST")
        self.codex = CodexProvider() if provider == "codex" else None
        self.complete = complete or (self.codex.complete if self.codex else cloudru.complete)
        self.allow_unconfigured = complete is not None
        self.models = Models(db,allow_system=complete is not None)
        self.jobs = {}
        self.locks = weakref.WeakValueDictionary()
        self.cache_locks = weakref.WeakValueDictionary()
        self.model_slots = asyncio.Semaphore(2)
        self.launch_lock = asyncio.Lock()
        self.closed = False

    async def initialize(self):
        Settings.load().validate()
        if self.codex and not self.allow_unconfigured:
            await self.codex.initialize()
        config = await self.rules.call("config")
        from .skills import instructions
        self.skills=instructions(config)
        self.sections=config['templateSections']

    def provider_status(self):
        return self.codex.status() if self.codex else {**cloudru.status(), "localTesting": False}

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
        fields = ("revision", "skeleton", "materials", "sections", "finalAssessment", "sources", "approval", "requirements", "structured", "answers")
        snapshot = copy.deepcopy({k: p.get(k) for k in fields})
        p["history"] = (p.get("history", []) + [{**snapshot, "at": now()}])[-15:]
        p["revision"] += 1

    async def load(self, id, owner):
        row = await self.query("one", "SELECT document FROM program_projects WHERE id=%s AND owner=%s", (id, owner))
        ensure(row, "Программа не найдена", 404)
        return row["document"]

    def idle(self, p):
        ensure(p["id"] not in self.jobs, "Дождитесь завершения текущей задачи или отмените её")

    async def references(self, p, query=""):
        rows = await self.query("all", "SELECT name,text,truncated FROM learning_materials WHERE id=ANY(%s) AND user_id=%s",
                                (p["referenceIds"], p["owner"]))
        keywords = set(re.findall(r"\w{4,}",query.lower()))
        result = []
        budget = 12000
        for row in rows:
            chunks = [row["text"][i:i+1400] for i in range(0,len(row["text"]),1400)]
            if keywords:
                chunks.sort(key=lambda text: -sum(word in text.lower() for word in keywords))
            excerpt = "\n".join(chunks[:4])[:min(6000,budget)]
            budget -= len(excerpt)
            result.append({**row,"text":excerpt,"trust":"untrusted-reference"})
            if budget <= 0:
                break
        return result

    async def call(self, p, skill, payload):
        connection = await self.models.selected(p["owner"])
        if connection:
            try:Settings.load().validate_endpoint(connection['base_url'],connection['model'])
            except ValueError as error:raise HTTPException(403,str(error)) from None
        profile = {"connectionId":connection["id"],"provider":connection["name"],"model":connection["model"],"localTesting":False,"personal":True} if connection else self.provider_status()
        cache_key = hashlib.sha256(json.dumps([3,profile.get("connectionId"),profile.get("model"),self.skills.get(skill,skill),payload],ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        async with self.cache_locks.setdefault((p['owner'],cache_key),asyncio.Lock()):
            return await self._call_locked(p,skill,payload,profile,connection,cache_key)

    async def _call_locked(self,p,skill,payload,profile,connection,cache_key):
        cached = await self.query("one", "SELECT value FROM llm_cache WHERE owner=%s AND digest=%s AND created>now()-interval '7 days'",(p["owner"],cache_key))
        if cached:
            p["usage"]["cacheHits"] = p["usage"].get("cacheHits",0)+1
            p["usage"].update(provider=profile["provider"],model=profile["model"],localTesting=profile["localTesting"])
            return cached["value"]
        try:
            async with self.model_slots:
                logger.info('llm_call_started',extra={'jobId':(p.get('job') or {}).get('id',''),'projectId':p['id'],'skill':skill})
                from .output_contracts import schema_for
                result = await self.models.complete(p["owner"],self.skills.get(skill,skill),payload,self.complete,selected=connection,response_schema=schema_for(skill,payload))
        except (ValueError,HTTPException) as error:
            if hasattr(error,'model_result'):
                await self.account_usage(p,error.model_result,profile,skill,'failed')
            if isinstance(error,HTTPException) and str(error.detail).startswith('Ответ обрезан.') and skill not in ('intake','intake_basic'):
                raise ValueError('Ответ обрезан поставщиком. Сократи необязательные пояснения; верни только JSON указанного урока/структуры, без повторения запроса и источников.') from None
            raise
        await self.account_usage(p,result,profile,skill)
        logger.info('llm_call_completed',extra={'jobId':(p.get('job') or {}).get('id',''),'projectId':p['id'],'skill':skill})
        cacheable=isinstance(result.get('value'),dict)
        if cacheable and skill in ('intake','intake_basic'):
            cacheable=not intake_issues(result['value'])
        elif cacheable and skill=='skeleton':
            cacheable=not (await self.rules.call('inspectSkeleton',result['value'],payload.get('requirements',{})))['errors']
        elif cacheable and skill in ('module','revise'):
            cacheable=not await self.rules.call('inspectModule',result['value'],payload['module'],payload['skeleton'])
        elif cacheable and skill=='outline':
            try:
                planned=build_skeleton(result['value'],payload['requirements'])
                cacheable=not (await self.rules.call('inspectSkeleton',planned,payload['requirements']))['errors']
            except (ValueError,ValidationError):cacheable=False
        elif cacheable and skill=='competency_repair':
            from .planning import repair_competencies
            try:repair_competencies(payload['outline'],result['value']['competencies'])
            except (KeyError,TypeError,ValueError,ValidationError):cacheable=False
        elif cacheable and skill=='sections':
            from .validation import inspect_sections
            from .regulations import section_policy_issues
            cacheable=not (inspect_sections(result['value'],payload['sectionTitles'])+section_policy_issues(result['value'],payload['skeleton']['type']))
            count=payload.get('requirements',{}).get('portfolioItems')
            if count and len((result['value'].get('finalAssessment') or {}).get('items',[]))!=count:cacheable=False
        elif cacheable and skill in ('lesson','assessment'):
            try:(Lecture if skill=='lesson' else LessonAssessment).model_validate(result['value'])
            except ValidationError:cacheable=False
        elif cacheable and skill in ('assignment','questions','interview'):
            key,contract={'assignment':('seminars',Seminar),'questions':('questions',TestQuestion),'interview':('interviews',Interview)}[skill]
            values=result['value'].get(key)
            cacheable=isinstance(values,list) and bool(values)
            if cacheable:
                try:
                    for value in values:contract.model_validate(value)
                except ValidationError:cacheable=False
        elif cacheable and skill=='standards':
            from .standards import standard_issue
            links=result['value'].get('links')
            cacheable=isinstance(links,list) and bool(links) and all(isinstance(x,dict) and x.get('reason') and not standard_issue(x) for x in links)
        elif cacheable and skill=='final_assessment':
            from .contracts import FinalAssessment
            try:FinalAssessment.model_validate(result['value'])
            except ValidationError:cacheable=False
            count=payload.get('requirements',{}).get('portfolioItems') or 0
            if len(result['value'].get('items',[]))!=count:cacheable=False
        if cacheable:
            await self.query("execute", "INSERT INTO llm_cache(owner,digest,value) VALUES(%s,%s,%s) ON CONFLICT(owner,digest) DO UPDATE SET value=excluded.value,created=now()",(p["owner"],cache_key,Jsonb(result["value"])))
            await self.query('execute',"DELETE FROM llm_cache WHERE owner=%s AND (created<now()-interval '7 days' OR digest NOT IN (SELECT digest FROM llm_cache WHERE owner=%s ORDER BY created DESC LIMIT 200))",(p['owner'],p['owner']))
        return result["value"]

    async def account_usage(self,p,result,profile,skill,status="completed"):
        from .usage import record
        counted=await record(self,p,result,profile,skill,status)
        usage = p["usage"]
        if "byProvider" not in usage:
            previous = "codex" if usage.get("localTesting") else "cloudru"
            usage["byProvider"] = {previous: {key: usage.get(key, 0) for key in ("inputTokens", "outputTokens", "calls")}}
        current_provider = profile.get("connectionId") or ("codex" if self.codex else "cloudru")
        ledger = usage["byProvider"].setdefault(current_provider, {"inputTokens": 0, "outputTokens": 0, "calls": 0})
        for key in ("inputTokens", "outputTokens"):
            usage[key] += counted[key]
            ledger[key] += counted[key]
        usage["calls"] += 1
        ledger["calls"] += 1
        usage["model"] = result.get("model") or profile["model"]
        usage["provider"] = profile["provider"]
        usage["localTesting"] = profile["localTesting"]
        incoming, outgoing = os.getenv("CLOUDRU_INPUT_RUB_PER_MILLION"), os.getenv("CLOUDRU_OUTPUT_RUB_PER_MILLION")
        cloud_usage = usage["byProvider"].get("cloudru", {})
        try:
            usage["estimatedRubles"] = (cloud_usage.get("inputTokens", 0) * float(incoming) + cloud_usage.get("outputTokens", 0) * float(outgoing)) / 1e6 if incoming and outgoing and not self.codex and not profile.get("personal") else None
        except ValueError:
            usage['estimatedRubles']=None

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
            logger.info('job_started',extra={'jobId':p['job']['id'],'projectId':p['id'],'stage':kind})
            try:
                async with asyncio.timeout(175 if kind in ("skeleton","intake") else 1180):
                    await work(p)
                p["job"]["state"] = "completed"
                p["job"]["completed"] = p["job"]["total"]
                await self.event(p, "job_completed", {"kind": kind})
                logger.info('job_completed',extra={'jobId':p['job']['id'],'projectId':p['id'],'stage':kind})
            except asyncio.CancelledError:
                p["job"].update(state="cancelled", error="Задача отменена. Готовые модули сохранены.")
            except Exception as error:
                message = error.detail if isinstance(error, HTTPException) else str(error)
                p["job"].update(state="failed", error=(message or "Превышено время выполнения задачи")[:500])
                p['job']['recovery']='Исправьте замечания или повторите этап. Готовые модули сохранены; согласование каркаса не выполняется автоматически.'
                logger.error('job_failed',extra={'jobId':p['job']['id'],'projectId':p['id'],'stage':kind,'errorType':type(error).__name__})
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
            existing=next((x for x in p['sources'] if (x.get('url') and x['url']==source.get('url')) or (not x.get('url') and x['title']==source['title'])),None)
            usage={k:source[k] for k in ('moduleId','topicId','reason') if source.get(k)}
            if existing:
                if usage and usage not in existing.setdefault('usages',[]):existing['usages'].append(usage)
            else:
                p["sources"].append({"id": str(uuid4()), "title": source["title"][:2000],
                                     "url": str(source.get("url") or "")[:3000], "kind": source.get("kind", "literature"),
                                     "reason":str(source.get("reason") or "Источник предложен моделью; требуется проверка содержания")[:1500],
                                     "moduleId":source.get("moduleId"),'usages':[usage] if usage else [], "verification": {"status": "unverified"}})

    async def action(self, action, body, user):
        owner = user["id"]
        if action == "status":
            from .exports import pptx_available
            return {**await self.models.status(owner,self.provider_status()), "pptx": pptx_available(), "skills": list(self.skills),
                    "humanApprovalRequired": True, "foreignProvidersEnabled": bool(self.codex)}
        if action == "list":
            rows = await self.query("all", "SELECT document FROM program_projects WHERE owner=%s AND COALESCE(document->>'demo','false')<>'true' ORDER BY updated DESC", (owner,))
            return [{"id": p["id"], "title": p.get("skeleton", {}).get("title") or p["request"][:90],
                     **{k: p.get(k) for k in ("state", "revision", "updatedAt", "demo", "job")}}
                    for row in rows for p in [row["document"]]]
        if action=='workflow' and not body.get('id'):
            created=await self.create('create',body,owner)
            return await self.action('workflow',{**body,'id':created['id']},user)
        if action in ("create", "demo"):
            ensure(action != "demo" or self.allow_unconfigured, "Демонстрационные программы отключены",404)
            return await self.create(action, body, owner)
        id = required(body.get("id"), 80)
        # Reject foreign/nonexistent IDs before allocating retained scheduler locks.
        await self.load(id,owner)
        # Serialize read-modify-write actions within this scheduler. Polling is also
        # serialized, so it never observes a half-applied user edit.
        async with self.locks.setdefault(id, asyncio.Lock()):
            p = await self.load(id, owner)
            if action == "get":
                events = await self.query("all", "SELECT action,detail,created FROM program_events WHERE project_id=%s AND owner=%s ORDER BY sequence DESC LIMIT 30", (id, owner))
                for event in events:
                    event["detail"] = json.dumps(event["detail"], ensure_ascii=False)
                from .reporting import workflow
                return {**p,'workflow':workflow(p), "report": await self.rules.call("inspectProgram", p) if p.get("skeleton") else None, "events": events}
            if action == "messages":
                from .chat import messages
                return await messages(self,p)
            if action == "cancel":
                task = self.jobs.get(id)
                ensure(task, "Активной задачи нет")
                task.cancel()
                await task
                return {"ok": True}
            if action == "delete":
                ensure(not await self.query("one", "SELECT 1 FROM publications WHERE project_id=%s",(id,)),"У программы есть опубликованная версия и история обучения. Удаление недоступно; переведите программу в приватный доступ.",409)
                ensure(body.get("confirm") is True, "Подтвердите удаление программы")
                task = self.jobs.get(id)
                if task:
                    task.cancel()
                    await task

                def remove():
                    with self.db.pool.connection() as connection:
                        row = connection.execute("SELECT id FROM program_projects WHERE id=%s AND owner=%s FOR UPDATE", (id, owner)).fetchone()
                        ensure(row, "Программа не найдена", 404)
                        connection.execute("DELETE FROM program_events WHERE project_id=%s", (id,))
                        connection.execute("DELETE FROM program_projects WHERE id=%s AND owner=%s", (id, owner))
                await asyncio.to_thread(remove)
                return {"ok": True, "id": id}
            self.idle(p)
            if action=='workflow':
                ensure(self.allow_unconfigured or (await self.models.status(owner,self.provider_status()))['configured'],'Настройте модель в профиле',503)
                p['workflowVersion']=3
                if p.get('approval'):
                    await self.approved(p)
                    return await self.launch(p,'generate',self.generate)
                if p.get('skeleton') and not body.get('answers'):
                    return p  # Human approval is a mandatory stop.
                answers=body.get('answers',{})
                ensure(isinstance(answers,dict) and len(json.dumps(answers))<12000,'Проверьте ответы')
                p['answers']={**p.get('answers',{}),**answers}
                return await self.launch(p,'intake',self.prepare)
            if action == "chat":
                from .chat import converse
                return await converse(self,p,body,owner)
            if action == "apply_proposal":
                from .chat import apply_proposal
                return await apply_proposal(self,p,body,owner)
            if action == "edit_module":
                module = next((m for m in p["skeleton"]["modules"] if m["id"] == body.get("moduleId")),None)
                ensure(module and body.get("expectedRevision") == p["revision"],"Обновите версию модуля",409)
                candidate = body.get("material")
                issues = await self.rules.call("inspectModule",candidate,module,p["skeleton"])
                ensure(not issues,"; ".join(x["message"] for x in issues[:3]))
                self.revision(p)
                p["materials"][module["id"]] = candidate
                await self.save(p)
                return p
            if action in ("analyze", "skeleton"):
                ensure(not p["demo"], "Демо не вызывает модель. Создайте новую программу.")
                ensure(self.allow_unconfigured or (await self.models.status(owner,self.provider_status()))["configured"], "Настройте модель в личном профиле", 503)
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
                p.update(skeleton=new, materials=kept, lessonDrafts={}, sections={}, finalAssessment=None, approval=None, state="skeleton_review")
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
                ensure(self.allow_unconfigured or (await self.models.status(owner,self.provider_status()))["configured"], "Провайдер модели не настроен", 503)
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
                for k in ('requirements','structured','answers'):
                    if k in snapshot:p[k]=copy.deepcopy(snapshot[k])
                p.update(approval=None, lessonDrafts={}, state="skeleton_review")
                await self.save(p)
                await self.event(p, "restored", {"revision": body["revision"]})
                return p
            if action == "export":
                ensure(p.get("skeleton"), "Нет каркаса для выгрузки")
                report = await self.rules.call("inspectProgram", p)
                if body.get("format") not in ('json','report'):
                    await self.approved(p)
                    ensure(report["passed"], "Исправьте ошибки автопроверки перед выгрузкой")
                topic_ids=body.get('topicIds')
                ensure(topic_ids is None or isinstance(topic_ids,list) and 1<=len(topic_ids)<=100 and all(isinstance(x,str) for x in topic_ids),'Проверьте список тем слайдов')
                response = await export_program({**p, "report": report, "templateSections": self.sections[p["skeleton"]["type"]]}, body.get("format"), body.get("moduleId"),topic_ids)
                await self.event(p, "export", {"format": body["format"]})
                return response
            raise HTTPException(422, "Неизвестная команда агента")

    async def create(self, action, body, owner):
        # Serialize the per-user quota and insertion in a PostgreSQL transaction.
        structured=body.get('requirements',{})
        ensure(isinstance(structured,dict),'Требования должны быть объектом')
        try:Requirements.model_validate(structured)
        except ValidationError:raise HTTPException(422,'Проверьте тип, часы и форму структурированных требований') from None
        references = body.get("referenceIds", [])
        ensure(isinstance(references, list) and len(references) <= 5 and all(isinstance(x, str) for x in references), "Добавьте не более пяти референсов")
        request = "Демонстрационный пример Python для школьников" if action == "demo" else required(body.get("request"), 20000)
        p = {"id": str(uuid4()), "owner": owner, "request": request, "referenceIds": references,
             "state": "brief", "revision": 1, "requirements": {}, "questions": [], "notes": [],
             "materials": {}, "sections": {}, "sources": [], "history": [], "job": None, "approval": None,
             "usage": {"inputTokens": 0, "outputTokens": 0, "calls": 0, "estimatedRubles": None},
             "createdAt": now(), "updatedAt": now(), "demo": action == "demo", "workflowVersion":3,
             "visibility":body.get("visibility","private"),"structured":body.get('requirements',{})}
        ensure(p["visibility"] in ("public","private"),"Выберите доступ программы")
        p["usage"].update(provider=self.provider_status()["provider"], localTesting=bool(self.codex))
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

    async def prepare(self,p):
        await self.analyze(p)
        if p['state']=='ready_for_skeleton':await self.skeleton(p)

    async def analyze(self, p):
        p["job"]["step"] = "Уточнение требований"
        if p.get('answers') and p.get('requirements'):
            # Canonical form answers do not need another paid semantic extraction.
            requirements,provenance=merge_requirements(p['request'],p['requirements'],p.get('structured'),p['answers'])
            missing=[k for k in CORE_QUESTIONS if not requirements.get(k)]
            questions=[{'field':k,'question':CORE_QUESTIONS[k]} for k in missing[:5]]
            schedule=schedule_question(requirements) if not missing else None
            if schedule:questions.append(schedule)
            p.update(requirements=requirements,requirementsProvenance=provenance,questions=questions,
                state='clarification' if questions else 'ready_for_skeleton')
            await self.save(p)
            return
        payload={"request": p["request"], "answers": p.get("answers", {}), "references": await self.references(p)}
        skill='intake_basic'
        for _ in range(2):
            try:
                data = await self.call(p, skill, payload)
                if isinstance(data,dict) and isinstance(data.get('requirements'),dict):
                    data['requirements'].update(explicit_requirements(p['request']))
                issues=intake_issues(data)
            except ValueError as error:
                if str(error)!='Модель вернула некорректный JSON':raise
                issues=['Верни только корректный JSON-объект без пояснений вне JSON']
                skill='intake_basic'
            except HTTPException as error:
                if not str(error.detail).startswith('Ответ обрезан.'):raise
                issues=['Сократи ответ: верни только requirements, questions, notes. Каркас будет создан отдельным шагом.']
                skill='intake_basic'
            if not issues:break
            payload={**payload,'validationErrors':issues,'instruction':'Исправь структуру ответа по контракту. Не добавляй необязательные вопросы.'}
        ensure(not issues, "Некорректный разбор запроса: "+'; '.join(issues))
        for question in data["questions"]:
            required(question.get("field"), 80)
            required(question.get("question"), 2000)
        parsed=Intake.model_validate(data)
        requirements,provenance=merge_requirements(p['request'],parsed.requirements.model_dump(exclude_none=True),p.get('structured'),p.get('answers'))
        p.update(requirements=requirements,requirementsProvenance=provenance,questions=[q.model_dump() for q in parsed.questions],notes=parsed.notes)
        missing_reference=not p.get('referenceIds') and bool(re.search(r'прикладываю|прикрепил|за образец|прошлую программу',p['request'],re.I))
        p['referenceStatus']={'attached':len(p.get('referenceIds',[])),'mentionedButMissing':missing_reference}
        if missing_reference:p['notes'].append('В запросе упомянут референс, но файл не прикреплён. Используется стандартный шаблон АЦР; структура невидимого документа не считается воспроизведённой.')
        if re.search(r'пойти\s+работать|трудоустро|стать\s+специалист',p['request'],re.I):
            p['notes'].append('Краткий курс формирует начальные прикладные навыки и не гарантирует трудоустройство или полную профессиональную квалификацию. Цели и входной уровень должен подтвердить методист.')
        data['skeleton']=parsed.skeleton
        count = re.search(r"(\d{1,3})\s+вопрос", p["request"], re.I)
        if count:
            p["requirements"]["testQuestionCount"] = int(count[1])
        needed = CORE_QUESTIONS
        missing = [k for k in needed if not p["requirements"].get(k)]
        # Ask only for missing mandatory fields; optional preferences do not block.
        aliases={'аудитория':'audience','уровень':'entryLevel','объём':'totalHours','объем':'totalHours',
                 'форма':'format','аттестация':'assessment','итоговая аттестация':'assessment','тип':'type','level':'entryLevel'}
        questions=[]
        for question in p['questions']:
            field=aliases.get(question['field'].lower(),question['field'])
            if field in missing and not any(q['field']==field for q in questions):
                questions.append({**question,'field':field})
        p['questions']=questions
        for field in missing:
            if len(p["questions"]) < 5 and not any(q["field"] == field for q in p["questions"]):
                p["questions"].append({"field": field, "question": needed[field]})
        schedule=schedule_question(p['requirements']) if not missing else None
        if schedule and len(p['questions'])<5:p['questions'].append(schedule)
        p["state"] = "clarification" if missing or p["questions"] else "ready_for_skeleton"
        if not missing and not p['questions'] and parsed.skeleton:
            # Compatible combined intake is accepted only after the SAME planner/checks.
            from .standards import normalize_standard
            try:
                candidate=build_skeleton(parsed.skeleton,p['requirements'])
                for c in candidate['competencies']:c['standard']=normalize_standard(c.get('standard'))
                report=await self.rules.call('inspectSkeleton',candidate,p['requirements'])
                if not report['errors']:
                    self.revision(p)
                    p.update(skeleton=candidate,materials={},lessonDrafts={},sections={},finalAssessment=None,approval=None,state='skeleton_review')
            except (ValueError,ValidationError):
                p['notes'].append('Предложенная структура требует исправления. Отдельный навык каркаса проверит требования повторно.')
        await self.save(p)

    async def skeleton(self, p):
        from .standards import candidates,normalize_standard
        p["job"]["step"] = "Карта компетенций и часы"
        candidate,issues=None,None
        for _ in range(2):
            try:
                candidate=await self.call(p,'outline',{'request':p['request'],'requirements':p['requirements'],
                    'availableStandards':candidates(p['request']+' '+p['requirements'].get('audience','')) if p['requirements']['type']=='dpp' else [],
                    'references':await self.references(p),'validationErrors':issues})
                from .planning import unresolved_competencies,repair_competencies
                missing_ids=unresolved_competencies(candidate)
                if missing_ids and len(missing_ids)<=40:
                    repaired=await self.call(p,'competency_repair',{'requirements':p['requirements'],
                        'outline':candidate,'missingIds':missing_ids})
                    candidate=repair_competencies(candidate,repaired.get('competencies',[]))
                candidate=build_skeleton(candidate,p['requirements'])
                if p.get('referenceStatus',{}).get('mentionedButMissing'):candidate['assumptions'].append('Упомянутый референс не прикреплён. Каркас использует стандартный шаблон АЦР; документ можно добавить перед доработкой.')
                for c in candidate['competencies']:c['standard']=normalize_standard(c.get('standard'))
                available=candidates(p['request']+' '+p['requirements'].get('audience','')) if p['requirements']['type']=='dpp' else []
                missing=[c for c in candidate['competencies'] if not c.get('standard')]
                if available and missing:
                    try:links=await self.call(p,'standards',{'competencies':missing,'availableStandards':available})
                    except (ValueError,HTTPException):
                        links={}
                        p.setdefault('notes',[]).append('Не удалось автоматически связать часть трудовых функций. Они явно отмечены как требующие экспертной проверки.')
                    allowed={(s['code'],function) for s in available for function in s['functions']}
                    from .standards import function_code
                    for link in (links.get('links') or []) if isinstance(links,dict) else []:
                        if not isinstance(link,dict) or (link.get('code'),function_code(link.get('functionCode'))) not in allowed or not link.get('reason'):continue
                        c=next((x for x in missing if x['id']==link.get('competencyId')),None)
                        if c:c['standard']={**normalize_standard(link),'mappingReason':str(link['reason'])[:2000]}
                report=await self.rules.call('inspectSkeleton',candidate,p['requirements'])
                issues=report['errors']
            except ValidationError as error:
                issues=[{'message':'.'.join(map(str,x['loc']))+': '+x['msg']} for x in error.errors(include_input=False,include_url=False)][:30]
            except ValueError as error:
                issues=[{'message':'Некорректный смысловой каркас: '+str(error)[:700]}]
            if not issues:break
        ensure(not issues, "Каркас не прошёл проверку: " + "; ".join(x["message"] for x in issues[:3]))
        self.revision(p)
        p.update(skeleton=candidate, materials={}, lessonDrafts={}, sections={}, finalAssessment=None, approval=None, state="skeleton_review")
        await self.save(p)

    async def generate(self, p, target=None, instruction=None):
        from .regulations import references as regulatory_references,section_policy_issues
        from .research import research
        p['workflowVersion']=3
        self.sources(p,regulatory_references(p['skeleton']['type']))
        if 'bibliography' not in p.setdefault('research',{}):
            query=p['skeleton']['title']+' '+', '.join(p['requirements'].get('requiredTopics',[]))
            p['research']['bibliography']=await research(query,await self.references(p,query))
        bibliography=p['research']['bibliography']
        self.sources(p,[{'title':x.get('title',x['url']),'url':x['url'],'kind':'documentation',
            'reason':'Первичная документация по тематике программы. '+('Текст получен; соответствие проверяет эксперт.' if x in bibliography.get('evidence',[]) else 'Текст недоступен автоматическому извлечению; ссылка НЕ ПОДТВЕРЖДЕНА и требует просмотра экспертом.')}
            for x in bibliography.get('evidence',[])+bibliography.get('unavailable',[])])
        for c in p['skeleton']['competencies']:
            if c.get('standard') and c['standard'].get('url'):
                self.sources(p,[{'title':c['standard']['title'],'url':c['standard']['url'],'kind':'professional_standard','reason':'Основание компетенции '+c['id']+'; функцию и применимость проверяет эксперт.'}])
        modules = [target] if target else p["skeleton"]["modules"]
        p["job"]["total"] = 1 if target else len(modules) + 1
        p["state"] = "generating"
        for index, module in enumerate(modules):
            p["job"].update(step="Материалы: " + module["title"], completed=index)
            await self.save(p)
            if not target and p["materials"].get(module["id"]) and not await self.rules.call("inspectModule", p["materials"][module["id"]], module, p["skeleton"],p['requirements'].get('currentControl')=='interview' or bool(p['requirements'].get('testQuestionCount'))):
                continue
            candidate, issues = None, None
            all_modules = p["skeleton"]["modules"]
            count = p["requirements"].get("testQuestionCount")
            # Spread the exact count over topics, avoiding artificial empty-topic quotas per module.
            all_topics=[t for m in all_modules for t in m['topics']]
            quotas={t['id']:count//len(all_topics)+(i<count%len(all_topics)) for i,t in enumerate(all_topics)} if count else {}
            quota=sum(quotas[t['id']] for t in module['topics']) if count else 0 if p['requirements'].get('currentControl')=='interview' else None
            if target:
                self.revision(p)
                p.setdefault('lessonDrafts',{}).pop(module['id'],None)
            candidate=await self.generate_lessons(p,module,quota,quotas,instruction)
            p['materials'][module['id']]=candidate
            for source in candidate.get('sources',[]):source['moduleId']=module['id']
            self.sources(p,candidate.get('sources'))
            await self.save(p)
        from .validation import inspect_sections
        titles=self.sections[p['skeleton']['type']]
        existing={'sections':canonicalize_sections(p.get('sections',{}),p['skeleton']),'finalAssessment':p.get('finalAssessment')}
        portfolio=p['requirements'].get('portfolioItems')
        existing_items=(p.get('finalAssessment') or {}).get('items',[])
        sections_valid=not (inspect_sections(existing,titles)+section_policy_issues(existing,p['skeleton']['type']))
        if portfolio and (len(existing_items)!=portfolio or any(not isinstance(x,dict) or not x.get('title') or not x.get('requirements') for x in existing_items)):sections_valid=False
        if not target and not sections_valid:
            p["job"]["step"] = "Разделы шаблона и итоговая аттестация"
            await self.save(p)
            from .validation import inspect_sections
            issues=None
            for attempt in range(2):
                try:
                    data = await self.call(p, "sections", {"request":p['request'],"skeleton": p["skeleton"], "sectionTitles": self.sections[p["skeleton"]["type"]], "requirements": p["requirements"], "knownSources": p["sources"],"regulatoryReferences":regulatory_references(p['skeleton']['type']),"validationErrors":issues})
                    data['sections']=canonicalize_sections(data.get('sections',{}),p['skeleton'])
                    if isinstance(data.get('finalAssessment'),dict):data['finalAssessment']['criteria']=normalize_criteria(data['finalAssessment'].get('criteria'))
                    items=p['requirements'].get('portfolioItems')
                    current=data.get('finalAssessment') or {}
                    if items and (len(current.get('items',[]))!=items or any(not isinstance(x,dict) or not x.get('title') or not x.get('requirements') for x in current.get('items',[]))):
                        correction=await self.call(p,'final_assessment',{'request':p['request'],'requirements':p['requirements'],'skeleton':p['skeleton'],
                            'instruction':f'Верни ровно {items} конкретных работ в items, каждая с title и requirements.'})
                        data['finalAssessment']=correction.get('finalAssessment',correction)
                        if isinstance(data['finalAssessment'],dict):data['finalAssessment']['criteria']=normalize_criteria(data['finalAssessment'].get('criteria'))
                    issues=inspect_sections(data,self.sections[p['skeleton']['type']])
                    issues+=section_policy_issues(data,p['skeleton']['type'])
                    if items and (len(data.get('finalAssessment',{}).get('items',[]))!=items or any(not isinstance(x,dict) or not x.get('title') or not x.get('requirements') for x in data['finalAssessment']['items'])):issues.append('В finalAssessment.items нужны '+str(items)+' работ портфолио {title,requirements}')
                except ValueError as error:issues=[str(error)[:600]]
                if not issues:break
            ensure(not issues, "Модель не заполнила разделы: "+'; '.join(issues[:3]))
            p.update(sections=data["sections"], finalAssessment=data["finalAssessment"])
            self.sources(p, data.get("sources"))
        elif not target:
            p['sections']=existing['sections']
        if p.get('workflowVersion',0)>=2:
            p['job']['step']='Проверка доступности источников'
            await self.save(p)
            semaphore=asyncio.Semaphore(4)
            async def check(source):
                evidence=next((x for collection in p.get('research',{}).values() for x in collection.get('evidence',[])
                    if x.get('url')==source.get('url') and x.get('status')=='fetched'),None)
                if evidence:
                    source['accessCheck']={'access':'reachable','status':'unverified','checkedAt':evidence.get('checkedAt'),
                        'method':'retrieved_document','note':'Текст получен при подготовке урока. Содержание и применимость подтверждает эксперт.'}
                    return
                async with semaphore:
                    source['accessCheck']=await probe_source(source)
            await asyncio.gather(*(check(source) for source in p['sources']))
        p["state"] = "draft_ready" if (await self.rules.call("inspectProgram", p))["passed"] else "needs_revision"
        await self.save(p)

    async def generate_lessons(self,p,module,quota,quotas=None,instruction=None):
        from .validation import inspect_module
        from .research import research
        saved=p.setdefault('lessonDrafts',{}).setdefault(module['id'],{})
        aggregate={'moduleId':module['id'],'summary':'','methodology':'','questions':[],'seminars':[],'interviews':[],'lectures':[],'sources':[]}
        for index,topic in enumerate(module['topics']):
            part={**module,'topics':[topic],'totalHours':topic['totalHours']}
            question_quota=(quotas or {}).get(topic['id'],quota//len(module['topics'])+(index<quota%len(module['topics']))) if quota is not None else None
            candidate=saved.get(topic['id'])
            needs_interview=p['requirements'].get('currentControl') in ('interview','mixed') or question_quota==0
            if not candidate or inspect_module(candidate,part,p['skeleton'],question_quota==0) or question_quota is not None and len(candidate.get('questions',[]))!=question_quota or needs_interview and not candidate.get('interviews'):
                p['job']['step']='Урок: '+topic['title'];await self.save(p)
                refs=await self.references(p,topic['title'])
                evidence=await research(topic['title']+' '+module['title'],refs)
                p.setdefault('research',{})[topic['id']]=evidence
                payload={'request':p['request'],'requirements':p['requirements'],'module':part,'questionQuota':question_quota,'instruction':instruction,
                         'competencies':[c for c in p['skeleton']['competencies'] if c['id'] in topic['competencyIds']],
                         'referenceExcerpts':refs,'webEvidence':evidence}
                candidate=candidate if isinstance(candidate,dict) else {}
                lectures=candidate.get('lectures',[])
                try:
                    if len(lectures)!=1:raise ValueError('Нужна одна лекция')
                    Lecture.model_validate(lectures[0])
                except (ValueError,ValidationError):
                    issues=None
                    for attempt in range(2):
                        try:
                            lecture=await self.call(p,'lesson',{**payload,'validationErrors':issues})
                            lecture=bind_lesson_item(lecture,topic,'lecture')
                            Lecture.model_validate(lecture)
                            if lecture['topicId']!=topic['id'] or not set(lecture['competencyIds'])<=set(topic['competencyIds']):
                                raise ValueError('Используй точные topicId и competencyIds из темы')
                            issues=None;break
                        except (ValueError,ValidationError) as error:issues=[{'message':str(error)[:1800]}]
                    ensure(not issues,'Лекция требует исправления: '+str(issues))
                    candidate={'moduleId':module['id'],'summary':lecture['title'],'methodology':'Изучение лекции, разбор примера и практическая работа.',
                               'lectures':[lecture],'questions':[],'seminars':[],'sources':[]}
                    saved[topic['id']]=candidate;await self.save(p)
                issues=None
                for attempt in range(2):
                    try:
                        assessed=await self.call(p,'assessment',{**payload,'lecture':candidate['lectures'][0], 'validationErrors':issues})
                        if isinstance(assessed,dict) and not assessed.get('seminars'):
                            practical=await self.call(p,'assignment',{**payload,'lecture':candidate['lectures'][0],
                                'instruction':'Подготовь проверяемое практическое упражнение, в том числе для вводного урока.'})
                            assessed['seminars']=practical.get('seminars',[])
                        expected=question_quota if question_quota is not None else 2
                        if isinstance(assessed,dict) and isinstance(assessed.get('questions',[]),list) and len(assessed.get('questions',[]))<expected:
                            bank=await self.call(p,'questions',{**payload,'lecture':candidate['lectures'][0],
                                'questionQuota':expected-len(assessed.get('questions',[])),
                                'previousQuestions':[q.get('text','') for q in assessed.get('questions',[]) if isinstance(q,dict)]})
                            assessed['questions']=assessed.get('questions',[])+bank.get('questions',[])
                        if isinstance(assessed,dict) and needs_interview and not assessed.get('interviews'):
                            oral=await self.call(p,'interview',{**payload,'lecture':candidate['lectures'][0]})
                            assessed['interviews']=oral.get('interviews',[])
                        for kind in ('questions','seminars','interviews'):
                            if isinstance(assessed.get(kind),list):assessed[kind]=[bind_lesson_item(x,topic,kind,i) for i,x in enumerate(assessed[kind],1)]
                        if question_quota is not None and isinstance(assessed.get('questions'),list) and len(assessed['questions'])>question_quota:
                            # Select the requested count from the generated bank rather
                            # than paying for an identical rewrite of excess questions.
                            assessed['questions']=assessed['questions'][:question_quota]
                        LessonAssessment.model_validate(assessed)
                        candidate.update(questions=assessed['questions'],seminars=assessed['seminars'],interviews=assessed.get('interviews',[]))
                        issues=inspect_module(candidate,part,p['skeleton'],question_quota==0)
                        if needs_interview and not candidate['interviews']:issues.append({'message':'Нужно собеседование interviews по теме с ожидаемыми ответами и критериями'})
                        if question_quota is not None and len(candidate['questions'])!=question_quota:
                            issues.append({'message':f'Нужно ровно {question_quota} вопросов'})
                    except (ValueError,ValidationError) as error:issues=[{'message':str(error)[:1800]}]
                    if not issues:break
                ensure(not issues,'Оценочные материалы требуют исправления: '+'; '.join(x['message'] for x in issues[:3]))
                # Only evidence actually fetched from a reference/search is added automatically.
                candidate['sources']=[{'title':x.get('title',x['url']),'url':x['url'],'kind':'documentation','topicId':topic['id'],
                    'reason':'Материал по теме '+topic['title']+'; доступность проверена при сборе, содержание требует экспертизы.'}
                    for x in evidence.get('evidence',[])]
                candidate['sources'] += [{'title':x.get('title',x['url']),'url':x['url'],'kind':'documentation','topicId':topic['id'],
                    'reason':'Ссылка из референса или тематического каталога для '+topic['title']+'. Текст автоматически не получен и не использован как подтверждённое доказательство; требуется проверка экспертом.'}
                    for x in evidence.get('unavailable',[])]
                saved[topic['id']]=candidate;await self.save(p)
                await self.event(p,'lesson_completed',{'moduleId':module['id'],'topicId':topic['id']})
            aggregate['summary']+=candidate['summary']+'\n'
            aggregate['methodology']+=candidate['methodology']+'\n'
            for kind in ('questions','seminars','lectures','interviews'):
                for position,item in enumerate(candidate.get(kind,[])):
                    aggregate[kind].append({**item,'id':f'{module["id"]}-{index+1}-{kind[0]}{position+1}'})
            aggregate['sources']+=candidate.get('sources',[])
        issues=inspect_module(aggregate,module,p['skeleton'],allow_empty_questions=quota is not None)
        ensure(not issues,'Модуль требует исправления: '+'; '.join(x['message'] for x in issues[:3]))
        return aggregate

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
