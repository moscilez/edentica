"""Roles, immutable approved course releases, expert review and learning workspaces."""
import asyncio
import copy
from datetime import datetime, timezone
import hashlib
import json
import re
from uuid import uuid4

from psycopg.types.json import Jsonb
from .programs_helpers import ensure, required


def content_digest(p):
    fields = ("skeleton", "materials", "sections", "finalAssessment", "sources", "requirements")
    return hashlib.sha256(json.dumps({k: p.get(k) for k in fields}, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def lessons(snapshot):
    result = []
    for mid, module in snapshot.get("materials", {}).items():
        for i, lecture in enumerate(module.get("lectures", [])):
            topic = lecture.get("topicId")
            questions = [q for q in module.get("questions", []) if q.get("topicId") == topic] if topic else (module.get("questions", []) if i == len(module["lectures"]) - 1 else [])
            result.append({"id": f"{mid}:{i}", "moduleId": mid, "title": lecture["title"],
                           "text": lecture.get("content") or lecture.get("plan", ""),
                           "slides": lecture.get("slides", []), "questions": questions})
    return result


def learner_lesson(lesson):
    return {**lesson, "questions": [{"id": q["id"], "text": q["text"], "options": q["options"]} for q in lesson["questions"]]}


def learning_issues(program):
    from .learning_content import lecture_issues
    issues=[]
    previous=[]
    for mid,module in program.get('materials',{}).items():
        for index,lecture in enumerate(module.get('lectures',[])):
            for message in lecture_issues(lecture,previous):
                issues.append(f"{mid}, урок {index+1}: {message}")
            previous.append(lecture)
    return issues


class Platform:
    def __init__(self, programs):
        self.programs, self.db = programs, programs.db

    async def query(self, method, *args):
        return await asyncio.to_thread(getattr(self.db, method), *args)

    def methodist(self, user):
        ensure(user["role"] == "methodist", "Действие доступно методисту", 403)

    async def owned(self, id, user):
        self.methodist(user)
        return await self.programs.load(required(id, 80), user["id"])

    async def release(self, id, user):
        row = await self.query("one", "SELECT * FROM publications WHERE id=%s", (id,))
        ensure(row, "Курс не найден", 404)
        if row["visibility"] != "public" and row["owner"] != user["id"] and row["expert"] != user["id"]:
            ensure(await self.query("one", "SELECT 1 FROM enrollments WHERE publication_id=%s AND user_id=%s", (id, user["id"])), "Курс не найден", 404)
        return row

    async def review_access(self, id, user):
        row = await self.query("one", "SELECT p.document,r.expert,r.status,r.digest FROM program_projects p LEFT JOIN program_reviews r ON r.project_id=p.id WHERE p.id=%s", (id,))
        ensure(row and user["id"] in (row["document"]["owner"], row["expert"]), "Программа не найдена", 404)
        if user['role']=='expert':
            report=await self.programs.rules.call('inspectProgram',row['document'])
            ensure(report['passed'] and not learning_issues(row['document']),
                   'Методист ещё готовит материалы. Проверка будет доступна после завершения курса.',409)
        return row

    async def action(self, action, data, user):
        uid = user["id"]
        if action in ('enroll','learning','lesson','complete_lesson','rate'):
            ensure(user['role'] != 'expert', 'Эксперт просматривает каталог и проверяет программы; обучение недоступно', 403)
        if action == "catalog":
            query = str(data.get("query", ""))[:200]
            return await self.query("all", """SELECT p.id,p.title,p.description,p.created,p.owner,u.name AS author,e.name AS expert,
                (p.snapshot->'skeleton'->>'totalHours') AS hours,
                COALESCE((SELECT avg(rating)::float FROM course_reviews WHERE publication_id=p.id),0) AS rating,
                (SELECT count(*) FROM enrollments WHERE publication_id=p.id) AS learners
                FROM publications p JOIN users u ON u.id=p.owner JOIN users e ON e.id=p.expert
                WHERE p.visibility='public' AND (p.title ILIKE %s OR p.description ILIKE %s)
                ORDER BY p.created DESC LIMIT 100""", ("%"+query+"%", "%"+query+"%"))
        if action == "course":
            row = await self.release(required(data.get("id"), 80), user)
            reviews = await self.query("all", "SELECT r.rating,r.comment,r.created,u.name FROM course_reviews r JOIN users u ON u.id=r.user_id WHERE publication_id=%s ORDER BY r.created DESC LIMIT 100", (row["id"],))
            authors = await self.query("all", "SELECT id,name FROM users WHERE id=ANY(%s)", ([row["owner"],row["expert"]],))
            return {**{k: row[k] for k in ("id","title","description","created","visibility","owner","expert")},
                    "skeleton": row["snapshot"]["skeleton"], "authors": authors, "reviews": reviews,
                    "lessons": [{"id": x["id"], "title": x["title"], "moduleId": x["moduleId"]} for x in lessons(row["snapshot"])]}
        if action == "similar":
            # Public catalogue retrieval is deterministic and consumes no model tokens.
            query = required(data.get("query"), 20000)
            tokens = set(re.findall(r"[\w+#]{3,}", query.lower()))
            rows = await self.action("catalog", {}, user)
            for row in rows:
                words = set(re.findall(r"[\w+#]{3,}", (row["title"]+" "+row["description"]).lower()))
                row["similarity"] = round(len(tokens & words) / max(1, min(len(tokens), len(words))), 2)
            return sorted([r for r in rows if r["similarity"] > .1], key=lambda r: -r["similarity"])[:5]
        if action == "copy":
            self.methodist(user)
            row = await self.release(required(data.get("id"), 80), user)
            ensure(row["visibility"] == "public" or row["owner"] == uid, "Можно копировать публичные программы", 403)
            p = await self.programs.create("create", {"request": "Адаптация: " + row["title"]}, uid)
            content = copy.deepcopy(row["snapshot"])
            p.update({k: content.get(k, {}) for k in ("skeleton","materials","sections","finalAssessment","sources","requirements")})
            p.update(state="skeleton_review", copiedFrom=row["id"], approval=None)
            for s in p.get("sources", []):
                s["verification"] = {"status":"unverified"}
            await self.programs.save(p)
            return p
        if action == "experts":
            return await self.query("all", "SELECT id,name,login FROM users WHERE role='expert' ORDER BY name LIMIT 200")
        if action == "review_queue":
            ensure(user["role"] == "expert", "Доступно эксперту", 403)
            return await self.query("all", "SELECT p.id,p.document->'skeleton'->>'title' AS title,r.status,p.updated FROM program_reviews r JOIN program_projects p ON p.id=r.project_id WHERE r.expert=%s ORDER BY p.updated DESC", (uid,))
        if action == "review":
            row = await self.review_access(required(data.get("id"), 80), user)
            comments = await self.query("all", "SELECT c.*,u.name FROM review_comments c JOIN users u ON u.id=c.author WHERE project_id=%s ORDER BY c.created", (data["id"],))
            return {"program": row["document"], "learningIssues":learning_issues(row['document']),"report":await self.programs.rules.call('inspectProgram',row['document']),"digest":content_digest(row["document"]), "status": row["status"], "expert": row["expert"], "current": row["digest"] == content_digest(row["document"]), "comments": comments}
        if action in ("request_review", "expert_decision", "publish", "visibility", "comment", "resolve_comment"):
            id = required(data.get("id"), 80)
            if action == "request_review":
                await self.owned(id,user)
            else:
                await self.review_access(id,user)
            async with self.programs.locks.setdefault(id, asyncio.Lock()):
                row = await self.review_access(id, user) if action != "request_review" else None
                p = row["document"] if row else await self.owned(id, user)
                self.programs.idle(p)
                digest = content_digest(p)
                if action == "request_review":
                    await self.programs.approved(p)
                    report = await self.programs.rules.call('inspectProgram', p)
                    ensure(report['passed'] and not learning_issues(p),
                           'Сначала завершите все модули, итоговую аттестацию и автопроверку. Затем отправьте готовый курс эксперту.', 409)
                    expert = required(data.get("expert"), 80)
                    ensure(expert != uid and await self.query("one", "SELECT 1 FROM users WHERE id=%s AND role='expert'", (expert,)), "Выберите другого пользователя с ролью эксперт")
                    await self.query("execute", "INSERT INTO program_reviews(project_id,expert,digest) VALUES(%s,%s,%s) ON CONFLICT(project_id) DO UPDATE SET expert=excluded.expert,digest=excluded.digest,status='pending',reviewed_at=NULL", (id, expert,digest))
                elif action == "comment":
                    message = required(data.get("message"), 6000)
                    await self.query("execute", "INSERT INTO review_comments(id,project_id,author,scope,message) VALUES(%s,%s,%s,%s,%s)", (str(uuid4()),id,uid,str(data.get("scope") or "program")[:100],message))
                elif action == "resolve_comment":
                    ensure(uid == p["owner"], "Доступно методисту", 403)
                    await self.query("execute", "UPDATE review_comments SET resolved=true WHERE id=%s AND project_id=%s", (required(data.get("commentId"),80),id))
                elif action == "expert_decision":
                    ensure(user["role"] == "expert" and row["expert"] == uid and uid != p["owner"], "Доступно назначенному эксперту", 403)
                    ensure(data.get("digest") == digest, "Содержание изменилось, перечитайте программу", 409)
                    status = data.get("status")
                    ensure(status in ("approved","changes_requested"), "Выберите решение")
                    report = await self.programs.rules.call("inspectProgram", p)
                    if status == "approved":
                        ensure(report["passed"], "Сначала исправьте ошибки программы")
                        ensure(not learning_issues(p),'; '.join(learning_issues(p)[:3]))
                        ensure(not await self.query("one", "SELECT 1 FROM review_comments WHERE project_id=%s AND resolved=false", (id,)), "Есть неразрешённые замечания")
                    await self.query("execute", "UPDATE program_reviews SET status=%s,digest=%s,reviewed_at=now() WHERE project_id=%s", (status,digest,id))
                elif action == "visibility":
                    self.methodist(user)
                    ensure(uid == p["owner"], "Недоступно", 403)
                    ensure(data.get("visibility") in ("public","private"), "Выберите доступ")
                    p["visibility"] = data["visibility"]
                    await self.query("execute", "UPDATE publications SET visibility=%s WHERE project_id=%s AND owner=%s",(data["visibility"],id,uid))
                    await self.programs.save(p)
                elif action == "publish":
                    self.methodist(user)
                    ensure(not p.get('demo'),'Тестовые примеры не публикуются')
                    ensure(uid == p["owner"], "Недоступно", 403)
                    ensure(data.get("confirm") is True and data.get("digest") == digest, "Подтвердите текущую версию", 409)
                    await self.programs.approved(p)
                    ensure(row["status"] == "approved" and row["digest"] == digest and row["expert"] != uid, "Нужно одобрение эксперта текущей версии", 409)
                    ensure((await self.programs.rules.call("inspectProgram", p))["passed"], "Исправьте ошибки программы")
                    ensure(not learning_issues(p),'; '.join(learning_issues(p)[:3]))
                    ensure(not await self.query("one", "SELECT 1 FROM review_comments WHERE project_id=%s AND resolved=false", (id,)), "Есть неразрешённые замечания")
                    snapshot = {k: copy.deepcopy(p.get(k)) for k in ("skeleton","materials","sections","sources","finalAssessment","requirements")}
                    publication = str(uuid4())
                    await self.query("execute", "INSERT INTO publications(id,project_id,owner,expert,digest,visibility,title,description,snapshot) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(project_id,digest) DO NOTHING", (publication,id,uid,row["expert"],digest,p.get("visibility","private"),p["skeleton"]["title"],p["skeleton"]["goal"],Jsonb(snapshot)))
                    return await self.query("one", "SELECT id FROM publications WHERE project_id=%s AND digest=%s", (id,digest))
                return {"ok":True, "digest":digest}
        if action == "rate":
            id = required(data.get("id"),80)
            row = await self.release(id,user)
            ensure(uid not in (row["owner"],row["expert"]), "Автор и эксперт не оценивают собственный курс",403)
            ensure(await self.query("one", "SELECT 1 FROM enrollments WHERE publication_id=%s AND user_id=%s", (id,uid)), "Сначала запишитесь на курс",403)
            ensure(type(data.get("rating")) is int and 1 <= data["rating"] <= 5, "Оценка от 1 до 5")
            await self.query("execute", "INSERT INTO course_reviews(publication_id,user_id,rating,comment) VALUES(%s,%s,%s,%s) ON CONFLICT(publication_id,user_id) DO UPDATE SET rating=excluded.rating,comment=excluded.comment,created=now()", (id,uid,data["rating"],required(data.get("comment"),2000)))
            return {"ok":True}
        if action == "enroll":
            row = await self.release(required(data.get("id"),80),user)
            ensure(row["visibility"] == "public", "На приватный курс назначает методист",403)
            await self.query("execute", "INSERT INTO enrollments(id,publication_id,user_id) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING", (str(uuid4()),row["id"],uid))
            return {"ok":True}
        if action == "learning":
            return await self.query("all", """SELECT e.*,p.title,
                (SELECT COALESCE(sum(jsonb_array_length(x.value->'lectures')),0) FROM jsonb_each(p.snapshot->'materials') x) AS total_lessons,
                (SELECT count(*) FROM lesson_progress l WHERE l.enrollment_id=e.id AND l.completed) AS completed,
                (SELECT avg(score)::float FROM lesson_progress l WHERE l.enrollment_id=e.id AND score IS NOT NULL) AS score
                FROM enrollments e JOIN publications p ON p.id=e.publication_id WHERE e.user_id=%s ORDER BY e.created DESC""", (uid,))
        if action in ("lesson", "complete_lesson"):
            enrollment = await self.query("one", "SELECT e.*,p.snapshot FROM enrollments e JOIN publications p ON p.id=e.publication_id WHERE e.id=%s AND e.user_id=%s", (required(data.get("enrollment"),80),uid))
            ensure(enrollment, "Назначение не найдено",404)
            units = lessons(enrollment["snapshot"])
            lesson = next((x for x in units if x["id"] == data.get("lessonId")), None)
            ensure(lesson, "Урок не найден",404)
            progress = await self.query("all", "SELECT lesson_id,completed,score,attempts FROM lesson_progress WHERE enrollment_id=%s",(enrollment["id"],))
            if action == "lesson":
                return {"lesson":learner_lesson(lesson),"outline":[{"id":x["id"],"title":x["title"]} for x in units],"progress":progress}
            answers = data.get("answers",{})
            ensure(isinstance(answers,dict),"Проверьте ответы")
            qs = lesson["questions"]
            ensure(all(type(answers.get(q["id"])) is int and 0 <= answers[q["id"]] < len(q["options"]) for q in qs), "Ответьте на все вопросы")
            score = round(100 * sum(answers[q["id"]] == q["answer"] for q in qs) / len(qs)) if qs else None
            completed = score is None or score >= 70
            await self.query("execute", "INSERT INTO lesson_progress(enrollment_id,lesson_id,completed,score,attempts) VALUES(%s,%s,%s,%s,1) ON CONFLICT(enrollment_id,lesson_id) DO UPDATE SET completed=lesson_progress.completed OR excluded.completed,score=GREATEST(lesson_progress.score,excluded.score),attempts=lesson_progress.attempts+1,updated=now()", (enrollment["id"],lesson["id"],completed,score))
            return {"completed":completed,"score":score,"passScore":70}
        if action == "groups":
            self.methodist(user)
            return await self.query("all", "SELECT g.*,(SELECT count(*) FROM group_members m WHERE m.group_id=g.id) AS members FROM study_groups g WHERE owner=%s ORDER BY created DESC", (uid,))
        if action == "create_group":
            self.methodist(user)
            id = str(uuid4())
            await self.query("execute", "INSERT INTO study_groups(id,owner,title) VALUES(%s,%s,%s)", (id,uid,required(data.get("title"),200)))
            return {"id":id}
        if action in ("add_member","assign","statistics"):
            self.methodist(user)
            group = required(data.get("groupId"),80)
            ensure(await self.query("one", "SELECT 1 FROM study_groups WHERE id=%s AND owner=%s", (group,uid)), "Группа не найдена",404)
            if action == "add_member":
                learner = await self.query("one", "SELECT id FROM users WHERE lower(login)=lower(%s) AND role='learner'", (required(data.get("login"),200),))
                ensure(learner, "Обучающийся с этим логином не найден",404)
                await self.query("execute", "INSERT INTO group_members(group_id,user_id) VALUES(%s,%s) ON CONFLICT DO NOTHING", (group,learner["id"]))
                return {"ok":True}
            if action == "assign":
                publication = await self.release(required(data.get("publicationId"),80),user)
                ensure(publication["owner"] == uid, "Назначайте опубликованные программы своего пространства",403)
                deadline = data.get("deadline")
                if deadline:
                    try:
                        deadline = datetime.fromisoformat(deadline.replace("Z","+00:00"))
                        ensure(deadline.tzinfo and deadline > datetime.now(timezone.utc), "Срок должен быть в будущем")
                    except (ValueError,TypeError):
                        ensure(False,"Некорректный срок")
                members = await self.query("all", "SELECT user_id FROM group_members WHERE group_id=%s",(group,))
                if data.get("login"):
                    target = await self.query("one", "SELECT id FROM users WHERE lower(login)=lower(%s)",(data["login"],))
                    members = [m for m in members if target and m["user_id"] == target["id"]]
                ensure(members,"Добавьте обучающихся в группу")
                for m in members:
                    await self.query("execute", "INSERT INTO enrollments(id,publication_id,user_id,assigned_by,group_id,deadline,required) VALUES(%s,%s,%s,%s,%s,%s,true) ON CONFLICT(publication_id,user_id) DO UPDATE SET assigned_by=excluded.assigned_by,group_id=excluded.group_id,deadline=excluded.deadline,required=true",(str(uuid4()),publication["id"],m["user_id"],uid,group,deadline))
                return {"assigned":len(members)}
            return await self.query("all", """SELECT u.name,u.login,e.id,e.publication_id,p.title,e.deadline,e.required,
                (SELECT COALESCE(sum(jsonb_array_length(x.value->'lectures')),0) FROM jsonb_each(p.snapshot->'materials') x) AS total_lessons,
                (SELECT count(*) FROM lesson_progress WHERE enrollment_id=e.id AND completed) AS completed,
                (SELECT avg(score)::float FROM lesson_progress WHERE enrollment_id=e.id AND score IS NOT NULL) AS score,
                (SELECT max(updated) FROM lesson_progress WHERE enrollment_id=e.id) AS last_activity
                FROM group_members m JOIN users u ON u.id=m.user_id LEFT JOIN enrollments e ON e.user_id=u.id AND e.group_id=m.group_id
                LEFT JOIN publications p ON p.id=e.publication_id WHERE m.group_id=%s ORDER BY u.name""",(group,))
        if action == 'course_statistics':
            self.methodist(user)
            publication = data.get('publicationId')
            if publication:
                ensure(await self.query('one', 'SELECT 1 FROM publications WHERE id=%s AND owner=%s', (required(publication,80),uid)), 'Курс не найден',404)
            return await self.query('all', """SELECT u.name,u.login,e.id,e.publication_id,p.title,e.created,e.deadline,e.required,
                CASE WHEN e.assigned_by IS NULL THEN 'self' ELSE 'assigned' END AS enrollment_type,
                g.title AS group_title,
                (SELECT COALESCE(sum(jsonb_array_length(x.value->'lectures')),0) FROM jsonb_each(p.snapshot->'materials') x) AS total_lessons,
                (SELECT count(*) FROM lesson_progress WHERE enrollment_id=e.id AND completed) AS completed,
                (SELECT avg(score)::float FROM lesson_progress WHERE enrollment_id=e.id AND score IS NOT NULL) AS score,
                (SELECT max(updated) FROM lesson_progress WHERE enrollment_id=e.id) AS last_activity
                FROM enrollments e JOIN publications p ON p.id=e.publication_id JOIN users u ON u.id=e.user_id
                LEFT JOIN study_groups g ON g.id=e.group_id
                WHERE p.owner=%s AND (%s::text IS NULL OR p.id=%s) ORDER BY p.title,u.name""", (uid,publication,publication))
        if action == "my_releases":
            return await self.query("all", "SELECT id,title,visibility,created FROM publications WHERE owner=%s ORDER BY created DESC", (uid,))
        ensure(False,"Неизвестное действие",404)
