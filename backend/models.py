"""Server-managed Cloud.ru access and transport. Personal model keys are not used."""
import asyncio
import json
import os
import re
from .net import public_request
from .programs_helpers import ensure
from .usage import reply_metadata,with_usage
from fastapi import HTTPException
from .config import Settings
from .observability import logger
import httpx


class Models:
    def __init__(self,db,allow_system=False):
        self.db=db;self.allow_system=allow_system

    async def selected(self,owner):
        # Legacy encrypted rows remain inert; no personal endpoint is resolved.
        return None

    async def system_allowed(self,owner):
        if self.allow_system or (os.getenv('EDENTICA_MODE')=='local' and os.getenv('HOST','127.0.0.1') in ('localhost','127.0.0.1','::1')):return True
        if os.getenv('SYSTEM_LLM_SHARED_ACCESS')=='1':return True
        allowed={x.strip().lower() for x in os.getenv('SYSTEM_LLM_ALLOWED_USERS','').split(',') if x.strip()}
        return owner.lower() in allowed

    async def status(self,owner,fallback):
        if not await self.system_allowed(owner):
            return {**fallback,'configured':False,'configurationHint':'Доступ к серверной модели Cloud.ru выдаёт администратор.'}
        return fallback

    async def complete(self,owner,skill,payload,fallback,selected=False,response_schema=None):
        ensure(not selected,'Личные подключения моделей отключены. Используется серверная модель Cloud.ru.',403)
        ensure(await self.system_allowed(owner),'Обратитесь к администратору для доступа к модели Cloud.ru',403)
        import inspect
        parameters=inspect.signature(fallback).parameters
        if 'response_schema' in parameters or any(p.kind==inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
            return await fallback(skill,payload,response_schema=response_schema)
        return await fallback(skill,payload)


async def compatible(base, key, model, skill, payload, max_tokens=None, *, allow_private=False, json_mode=False,response_schema=None):
    request_payload={"model": model, "stream": False, "temperature": .2,
                 **({'max_tokens':max_tokens} if max_tokens is not None else {}),
                 **({'response_format':{'type':'json_object'}} if json_mode else {}),
                 "messages": [{"role": "system", "content": skill},
                              {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}]}
    if response_schema and Settings.load().structured_output:
        request_payload['response_format']={'type':'json_schema','json_schema':{'name':'educational_material','strict':True,'schema':response_schema}}
    for attempt in range(3):
        try:
            code, headers, raw = await public_request("POST", base.rstrip("/") + "/chat/completions",
        headers={"Authorization": "Bearer " + key}, timeout=150, limit=3000000, allow_private=allow_private,
                payload=request_payload)
        except (httpx.TransportError,TimeoutError):
            if attempt==2:raise HTTPException(503,'Нет связи с моделью. Результаты сохранены; повторите этап позже.') from None
            code=503;headers={}
        if code==400 and request_payload.get('response_format',{}).get('type')=='json_schema' and attempt<2:
            logger.warning('structured_output_unavailable',extra={'status':code})
            request_payload['response_format']={'type':'json_object'}
            continue  # Provider capability fallback; local validation is mandatory.
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
