"""Per-user encrypted OpenAI-compatible connections; secrets never leave this service."""
import asyncio
import json
import os
import re
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from psycopg import IntegrityError
from .net import public_request, public_url
from .programs_helpers import ensure, required
from .usage import reply_metadata, with_usage
from fastapi import HTTPException
from .config import Settings
from .observability import logger
import httpx


def cipher():
    key = os.getenv("APP_ENCRYPTION_KEY", "")
    ensure(key, "Администратор должен настроить APP_ENCRYPTION_KEY для хранения ключей", 503)
    try:
        return Fernet(key.encode())
    except ValueError:
        raise ValueError("Некорректный ключ шифрования сервера") from None


class Models:
    def __init__(self, db, allow_system=False):
        self.db = db
        self.allow_system=allow_system

    async def query(self, method, *args):
        return await asyncio.to_thread(getattr(self.db, method), *args)

    async def selected(self, owner):
        return await self.query("one", "SELECT * FROM model_connections WHERE user_id=%s AND enabled ORDER BY created DESC LIMIT 1", (owner,))

    async def system_allowed(self,owner):
        if self.allow_system or (os.getenv('EDENTICA_MODE')=='local' and os.getenv('HOST','127.0.0.1') in ('localhost','127.0.0.1','::1')):
            return True
        if os.getenv('SYSTEM_LLM_SHARED_ACCESS')=='1':
            return True
        allowed={x.strip().lower() for x in os.getenv('SYSTEM_LLM_ALLOWED_USERS','').split(',') if x.strip()}
        if not allowed:return False
        return owner.lower() in allowed

    async def status(self, owner, fallback):
        row = await self.selected(owner)
        if not row:
            if not await self.system_allowed(owner):
                return {**fallback,'configured':False,'configurationHint':'Добавьте личное подключение ИИ. Доступ к ключу сервера выдаёт администратор.'}
            return fallback
        try:Settings.load().validate_endpoint(row['base_url'],row['model'])
        except ValueError as error:
            return {'provider':row['name'],'model':row['model'],'configured':False,'localTesting':False,
                    'blocked':True,'configurationHint':str(error)}
        return {"provider": row["name"], "model": row["model"], "configured": True, "localTesting": False,
                "connectionId": row["id"], "personal": True}

    async def list(self, owner):
        return await self.query("all", "SELECT id,name,base_url,model,enabled,output_limit,created FROM model_connections WHERE user_id=%s ORDER BY created DESC", (owner,))

    async def save(self, owner, data):
        name, model = required(data.get("name"), 80), required(data.get("model"), 200)
        base = required(data.get("baseUrl"), 500).rstrip("/")
        try:Settings.load().validate_endpoint(base,model)
        except ValueError as error:ensure(False,str(error),403)
        try:
            parsed,_=public_url(base)
            ensure(not parsed.query,'Base URL указывается без параметров запроса')
        except ValueError as e:
            ensure(False,str(e))
        key = required(data.get("apiKey"), 4000)
        ensure("\n" not in key and "\r" not in key, "Некорректный ключ")
        output = data.get("outputLimit", 6000)
        ensure(type(output) is int and 1000 <= output <= 16000, "Лимит ответа: 1000–16000 токенов")
        encrypted = cipher().encrypt(key.encode()).decode()
        def write():
            with self.db.pool.connection() as c:
                c.execute("SELECT id FROM users WHERE id=%s FOR UPDATE", (owner,))
                ensure(c.execute("SELECT count(*) AS n FROM model_connections WHERE user_id=%s", (owner,)).fetchone()["n"] < 5, "Не более пяти подключений")
                c.execute("UPDATE model_connections SET enabled=false WHERE user_id=%s", (owner,))
                c.execute("INSERT INTO model_connections(id,user_id,name,base_url,model,encrypted_key,output_limit) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                          (str(uuid4()), owner, name, base, model, encrypted, output))
        try:
            await asyncio.to_thread(write)
        except IntegrityError:
            ensure(False,"Подключение с таким названием уже существует",409)
        return await self.list(owner)

    async def remove(self, owner, id):
        await self.query("execute", "DELETE FROM model_connections WHERE id=%s AND user_id=%s", (id, owner))
        return {"ok": True}

    async def complete(self, owner, skill, payload, fallback, selected=False):
        row = await self.selected(owner) if selected is False else selected
        if row:
            try:Settings.load().validate_endpoint(row['base_url'],row['model'])
            except ValueError as error:ensure(False,str(error),403)
            try:
                key = cipher().decrypt(row["encrypted_key"].encode()).decode()
            except InvalidToken:
                raise ValueError("Не удалось расшифровать подключение. Проверьте ключ сервера.") from None
            result = await compatible(row["base_url"], key, row["model"], skill, payload)
            result["connection"] = row["id"]
            return result
        ensure(await self.system_allowed(owner),'Добавьте личное подключение ИИ или запросите у администратора доступ к модели сервера',403)
        return await fallback(skill, payload)


async def compatible(base, key, model, skill, payload, max_tokens=None, *, allow_private=False, json_mode=False):
    request_payload={"model": model, "stream": False, "temperature": .2,
                 **({'max_tokens':max_tokens} if max_tokens is not None else {}),
                 **({'response_format':{'type':'json_object'}} if json_mode else {}),
                 "messages": [{"role": "system", "content": skill},
                              {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}]}
    for attempt in range(3):
        try:
            code, headers, raw = await public_request("POST", base.rstrip("/") + "/chat/completions",
        headers={"Authorization": "Bearer " + key}, timeout=150, limit=3000000, allow_private=allow_private,
                payload=request_payload)
        except (httpx.TransportError,TimeoutError):
            if attempt==2:raise HTTPException(503,'Нет связи с моделью. Результаты сохранены; повторите этап позже.') from None
            code=503;headers={}
        if code not in (408,429,500,502,503,504) or attempt==2:break
        logger.warning('llm_retry',extra={'attempt':attempt+1,'status':code})
        retry=headers.get('retry-after','')
        delay=min(float(retry),5) if retry.isdigit() else .5*(2**attempt)
        await asyncio.sleep(delay)
    ensure(200 <= code < 300, f"Модель вернула HTTP {code}. Проверьте адрес, модель и квоту.", 502)
    metadata={}
    try:
        data = json.loads(raw)
        metadata=reply_metadata(data,model)
        choice = data["choices"][0]
        if choice.get('finish_reason')=='length':
            raise with_usage(HTTPException(422,'Ответ обрезан. Лимит установил поставщик. Разбейте задачу или измените настройки модели у поставщика.'),metadata)
        text = choice["message"]["content"]
        value = json.loads(re.sub(r"\s*```\s*$", "", re.sub(r"^\s*```(?:json)?\s*", "", text)))
        if not isinstance(value,dict):raise ValueError()
        return {"value":value,**metadata}
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        error=ValueError('Модель вернула некорректный JSON')
        raise with_usage(error,metadata) from None
