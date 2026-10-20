"""Same-origin FastAPI server for the Edentica hackathon workspace."""
import asyncio
import base64
from contextlib import asynccontextmanager
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sys
import time
from urllib.parse import urlsplit
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, Response
from psycopg import IntegrityError

from .database import Database, ROOT
from .exports import subprocess_bytes
from .programs import Programs, required, ensure
from .rules import Rules
from .platform import Platform

load_dotenv(ROOT / ".env")
logger = logging.getLogger("edentica")


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    # Preserve the Node scrypt encoding so imported accounts retain their passwords.
    return salt + ":" + hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=64).hex()


def check_password(password, stored):
    try:
        salt, _ = stored.split(":", 1)
        return hmac.compare_digest(hash_password(password, salt), stored)
    except (ValueError, TypeError):
        return False


def create_app(database_url=None, complete=None):
    @asynccontextmanager
    async def lifespan(app):
        public=urlsplit(os.getenv('PUBLIC_URL','http://localhost:3000'))
        if public.hostname not in ('localhost','127.0.0.1','::1',None):
            if public.scheme!='https' or os.getenv('COOKIE_SECURE')!='1':
                raise RuntimeError('Для публичного адреса нужны HTTPS PUBLIC_URL и COOKIE_SECURE=1')
        app.state.db = Database(database_url)
        try:
            await asyncio.to_thread(app.state.db.open)
            app.state.programs = Programs(app.state.db, Rules(), complete)
            await app.state.programs.initialize()
            app.state.platform = Platform(app.state.programs)
            app.state.models = app.state.programs.models
            yield
        finally:
            if hasattr(app.state, "programs"):
                await app.state.programs.close()
            await asyncio.to_thread(app.state.db.close)

    app = FastAPI(title="Edentica", version="0.5.0", lifespan=lifespan, docs_url=None, redoc_url=None)
    limits, imports = {}, 0

    async def db(method, *args):
        return await asyncio.to_thread(getattr(app.state.db, method), *args)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def error(request, exc):
        logger.error("Request failed: %s", type(exc).__name__)
        return JSONResponse({"error": "Внутренняя ошибка сервера"}, status_code=500)

    @app.middleware("http")
    async def protections(request, call_next):
        response = None
        try:
            host = urlsplit("http://" + request.headers.get("host", "localhost")).hostname
            allowed = {"localhost", "127.0.0.1", "::1", *filter(None, (s.strip().lower() for s in os.getenv("ALLOWED_HOSTS", "").split(",")))}
            if os.getenv("PUBLIC_URL"):
                allowed.add(urlsplit(os.environ["PUBLIC_URL"]).hostname)
            ensure(host in allowed, "Недопустимый адрес сервера", 403)
            if request.url.path.startswith("/api/"):
                ensure(request.method in ("GET", "POST"), "Метод не разрешён", 405)
                if request.method != "GET":
                    origin = request.headers.get("origin")
                    expected = request.headers.get("host")
                    ensure(not origin or origin in ("http://" + expected, "https://" + expected), "Запрос запрещён", 403)
                    ensure(request.headers.get("x-edentica") == "1", "Запрос запрещён", 403)
                    chunks, size = [], 0
                    maximum = 7000000 if request.url.path == "/api/materials" else 200000
                    async for chunk in request.stream():
                        size += len(chunk)
                        ensure(size <= maximum, "Слишком большой запрос", 413)
                        chunks.append(chunk)
                    request._body = b"".join(chunks)
                category = "auth" if "/auth/" in request.url.path else "api"
                identity = request.client.host if request.client else "local"
                if category == "api" and request.cookies.get('session'):
                    account = await user(request,False)
                    if account:
                        identity = 'user:'+account['id']
                key = (identity,category)
                stamp = time.monotonic()
                count, until = limits.get(key, (0, 0))
                if stamp > until:
                    count, until = 0, stamp + 60
                limits[key] = (count + 1, until)
                ensure(count < (20 if key[1] == "auth" else 200), "Слишком много запросов", 429)
                if len(limits) > 10000:
                    for expired in [k for k, v in limits.items() if v[1] < stamp]:
                        del limits[expired]
            response = await call_next(request)
        except HTTPException as error:
            response = JSONResponse({"error": error.detail}, status_code=error.status_code)
        response.headers.update({"X-Content-Type-Options": "nosniff", "Referrer-Policy": "same-origin", "Cache-Control": "no-store",
                                 "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return response

    async def body(request):
        try:
            data = await request.json()
        except (ValueError, UnicodeError):
            raise HTTPException(400, "Некорректный JSON") from None
        ensure(isinstance(data, dict), "Ожидается JSON-объект", 400)
        return data

    async def user(request, login=True):
        if getattr(request.state,'user_loaded',False):
            account=request.state.account
            ensure(account or not login,"Войдите в аккаунт",401)
            return account
        token = request.cookies.get("session")
        account = await db("one", """SELECT u.id,u.name,u.email,u.login,u.role FROM users u JOIN sessions s ON s.user_id=u.id
            WHERE s.token=%s AND s.expires>%s AND NOT EXISTS(SELECT 1 FROM user_suspensions b WHERE b.user_id=u.id)""",
                           (hashlib.sha256(token.encode()).hexdigest(), int(time.time() * 1000))) if token else None
        ensure(account or not login, "Войдите в аккаунт", 401)
        request.state.user_loaded=True
        request.state.account=account
        return account

    @app.get("/api/health")
    async def health():
        await db("one", "SELECT 1")
        return {"service": "edentica", "status": "ready", "backend": "python", "database": "postgresql",
                'workflowVersion':3,'modelConfigured':bool(app.state.programs.provider_status()['configured'])}

    @app.get("/api/me")
    async def me(request: Request):
        account = await user(request, False)
        return {"user": account, "admin": bool(account and account["id"] == os.getenv("ADMIN_USER_ID")), "xp": 0}

    @app.post("/api/auth/{action}")
    async def auth(action: str, request: Request):
        data = await body(request)
        if action == "logout":
            token = request.cookies.get("session")
            if token:
                await db("execute", "DELETE FROM sessions WHERE token=%s", (hashlib.sha256(token.encode()).hexdigest(),))
            response = JSONResponse({"ok": True})
            response.delete_cookie("session", httponly=True, samesite="lax", secure=os.getenv("COOKIE_SECURE") == "1")
            return response
        ensure(action in ("login", "register"), "Не найдено", 404)
        login, password = required(data.get("login") or data.get("email")).lower(), required(data.get("password"), 128)
        ensure(re.fullmatch(r"[\w.@+\-]{3,100}", login), "Логин: 3–100 букв, цифр, точек, дефисов или @")
        account = await db("one", "SELECT * FROM users WHERE lower(login)=%s", (login,))
        if action == "register":
            ensure(len(password) >= 10, "Пароль должен содержать минимум 10 символов")
            ensure(not account, "Логин уже зарегистрирован", 409)
            role = data.get("role", "methodist")
            ensure(role in ("methodist", "expert", "learner"), "Выберите роль")
            email = login if "@" in login else login + "@users.edentica.invalid"
            account = {"id": str(uuid4()), "name": required(data.get("name"), 100), "email": email, "login":login,"role":role}
            hashed = await asyncio.to_thread(hash_password, password)
            try:
                await db("execute", "INSERT INTO users(id,name,email,password,login,role) VALUES(%s,%s,%s,%s,%s,%s)",
                         (account["id"], account["name"], email, hashed,login,role))
            except IntegrityError:
                raise HTTPException(409, "Email уже зарегистрирован") from None
        else:
            valid = await asyncio.to_thread(check_password, password, account["password"] if account else "0000000000000000:" + "00" * 64)
            ensure(account and valid, "Неверный email или пароль", 401)
        ensure(not await db("one", "SELECT 1 FROM user_suspensions WHERE user_id=%s", (account["id"],)), "Аккаунт заблокирован", 403)
        token = secrets.token_hex(32)
        await db("execute", "INSERT INTO sessions(token,user_id,expires) VALUES(%s,%s,%s)",
                 (hashlib.sha256(token.encode()).hexdigest(), account["id"], int(time.time() * 1000) + 604800000))
        response = JSONResponse({k: account[k] for k in ("id", "name", "email", "login", "role")})
        response.set_cookie("session", token, max_age=604800, httponly=True, samesite="lax", secure=os.getenv("COOKIE_SECURE") == "1")
        return response

    @app.get('/api/usage')
    async def usage(request: Request):
        account=await user(request)
        try:days=int(request.query_params.get('days','30'))
        except ValueError:raise HTTPException(422,'Период должен быть числом дней') from None
        ensure(1<=days<=366,'Период: от 1 до 366 дней')
        timezone=request.query_params.get('timezone','Europe/Moscow')
        ensure(len(timezone)<=100 and await db('one','SELECT name FROM pg_timezone_names WHERE name=%s',(timezone,)),
               'Неизвестный часовой пояс')
        from .usage import summary
        return await summary(db,account['id'],days,timezone)

    @app.post("/api/profile")
    async def profile(request: Request):
        account = await user(request)
        data = await body(request)
        if data.get('action')=='password':
            current=required(data.get('currentPassword'),128)
            new=required(data.get('newPassword'),128)
            ensure(len(new)>=10,'Пароль должен содержать минимум 10 символов')
            row=await db('one','SELECT password FROM users WHERE id=%s',(account['id'],))
            ensure(await asyncio.to_thread(check_password,current,row['password']),'Текущий пароль неверен',403)
            hashed=await asyncio.to_thread(hash_password,new)
            def change():
                with app.state.db.pool.connection() as connection:
                    connection.execute('UPDATE users SET password=%s WHERE id=%s',(hashed,account['id']))
                    connection.execute('DELETE FROM sessions WHERE user_id=%s',(account['id'],))
            await asyncio.to_thread(change)
            response=JSONResponse({'ok':True,'signInRequired':True})
            response.delete_cookie('session',httponly=True,samesite='lax',secure=os.getenv('COOKIE_SECURE')=='1')
            return response
        name = required(data.get("name"),100)
        login = required(data.get("login"),100).lower()
        ensure(re.fullmatch(r"[\w.@+\-]{3,100}", login), "Проверьте логин")
        try:
            await db("execute", "UPDATE users SET name=%s,login=%s WHERE id=%s",(name,login,account["id"]))
        except IntegrityError:
            raise HTTPException(409,"Логин занят") from None
        return {**account,"name":name,"login":login}

    @app.post("/api/connections")
    async def connections(request: Request):
        account = await user(request)
        ensure(account["role"] == "methodist", "Настройки ИИ доступны методисту",403)
        data = await body(request)
        if data.get("action") == "save":
            return await app.state.models.save(account["id"],data)
        if data.get("action") == "remove":
            return await app.state.models.remove(account["id"],required(data.get("id"),80))
        if data.get("action") == "select":
            id = data.get("id")
            def select():
                with app.state.db.pool.connection() as c:
                    c.execute("SELECT id FROM users WHERE id=%s FOR UPDATE",(account["id"],))
                    ensure(not id or c.execute("SELECT 1 FROM model_connections WHERE id=%s AND user_id=%s",(id,account["id"])).fetchone(),"Подключение не найдено",404)
                    c.execute("UPDATE model_connections SET enabled=(id=%s) WHERE user_id=%s",(id or "",account["id"]))
            await asyncio.to_thread(select)
        return await app.state.models.list(account["id"])

    @app.post("/api/platform")
    async def platform(request: Request):
        account = await user(request)
        data = await body(request)
        result = await app.state.platform.action(required(data.get("action"),40),data,account)
        return JSONResponse(jsonable_encoder(result))

    @app.post("/api/lesson-export")
    async def lesson_export(request: Request):
        account=await user(request)
        data=await body(request)
        ensure(account["role"]=="methodist","Доступно методисту",403)
        program=await app.state.programs.load(required(data.get("id"),80),account["id"])
        await app.state.programs.approved(program)
        from .lesson_exports import export_lesson
        return await asyncio.to_thread(export_lesson,program,required(data.get("lessonId"),100),data.get("format"))

    @app.api_route('/api/programs',methods=['GET','POST'])
    @app.api_route("/api/agent", methods=["GET", "POST"])
    async def agent(request: Request):
        account = await user(request)
        ensure(account["role"] == "methodist", "Создание программ доступно методисту",403)
        data = await body(request) if request.method == "POST" else {}
        if request.url.path=='/api/programs':
            data=await body(request) if request.method=='POST' else dict(request.query_params)
            action=data.get('action') or ('workflow' if request.method=='POST' else 'get' if data.get('id') else 'list')
        else:action = required(data.get("action"), 40) if request.method == "POST" else "status"
        try:
            result = await app.state.programs.action(action, data, account)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        if isinstance(result, Response):
            return result
        return JSONResponse(jsonable_encoder(result), status_code=201 if action in ("create", "demo") else 200)

    @app.api_route("/api/materials", methods=["GET", "POST"])
    async def materials(request: Request):
        nonlocal imports
        account = await user(request)
        if request.method == "GET":
            return await db("all", "SELECT id,name,kind,size,truncated,created FROM learning_materials WHERE user_id=%s ORDER BY created DESC", (account["id"],))
        ensure(imports < 2, "Сейчас обрабатываются другие файлы. Повторите позже.", 429)
        data = await body(request)
        name = required(data.get("name"), 200)
        kind = name.rsplit(".", 1)[-1].lower()
        ensure(kind in ("txt", "docx", "pdf", "pptx"), "Поддерживаются PDF, DOCX, PPTX и UTF-8 TXT")
        try:
            content = base64.b64decode(data.get("data", ""), validate=True)
        except (ValueError, TypeError):
            raise HTTPException(422, "Некорректный файл") from None
        ensure(0 < len(content) <= 5000000, "Файл до 5 МБ")
        imports += 1
        try:
            result = json.loads(await subprocess_bytes([sys.executable, str(ROOT / "scripts/extract-material.py"), kind], content, timeout=20, maximum=300000))
        except (ValueError, asyncio.TimeoutError):
            raise HTTPException(422, "Не удалось прочитать файл. Проверьте формат и наличие текста.") from None
        finally:
            imports -= 1
        id = str(uuid4())
        def insert():
            with app.state.db.pool.connection() as connection:
                connection.execute("SELECT id FROM users WHERE id=%s FOR UPDATE", (account["id"],))
                ensure(connection.execute("SELECT count(*) AS n FROM learning_materials WHERE user_id=%s", (account["id"],)).fetchone()["n"] < 30, "Лимит библиотеки: 30 материалов")
                connection.execute("INSERT INTO learning_materials(id,user_id,name,kind,size,text,truncated) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                                   (id, account["id"], name, kind, len(content), result["text"], int(result["truncated"])))
        await asyncio.to_thread(insert)
        return JSONResponse({"id": id, **result}, status_code=201)

    @app.get("/api/materials/{id}")
    async def material(id: str, request: Request):
        account = await user(request)
        row = await db("one", "SELECT * FROM learning_materials WHERE id=%s AND user_id=%s", (id, account["id"]))
        ensure(row, "Материал не найден", 404)
        return row

    @app.post("/api/materials/{id}/remove")
    async def remove(id: str, request: Request):
        account = await user(request)
        data = await body(request)
        ensure(data.get("confirm") is True, "Подтвердите удаление материала")
        ensure(await db("execute", "DELETE FROM learning_materials WHERE id=%s AND user_id=%s", (id, account["id"])), "Материал не найден", 404)
        return {"ok": True}

    @app.api_route("/api/{path:path}", methods=["GET", "POST"])
    async def unavailable(path: str):
        raise HTTPException(410, "Этот маршрут прежней LMS не используется в студии образовательных программ")

    @app.get("/")
    @app.get("/programs")
    async def index():
        return FileResponse(ROOT / "public/program-studio.html", media_type="text/html")

    @app.get("/{asset}")
    async def assets(asset: str):
        allowed = {"brand.svg", "brand.png", "favicon.svg", "favicon.png", "favicon.ico",
                   "program-studio.js", "program-studio.css", "program-editor.js", "workspace.js", "usage.js", "workspace.css"}
        ensure(asset in allowed, "Не найдено", 404)
        return FileResponse(ROOT / "public" / asset)

    return app


app = create_app()
