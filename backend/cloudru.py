import json
import os
import re
import httpx
from .usage import reply_metadata, with_usage

ENDPOINT = "https://foundation-models.api.cloud.ru/v1"


def status():
    return {"provider": "LLM шлюз" if os.getenv("LLM_BASE_URL") else "Cloud.ru Evolution Foundation Models", "endpoint": os.getenv("LLM_BASE_URL") or ENDPOINT,
            "configured": bool((os.getenv("LLM_API_KEY") or os.getenv("CLOUDRU_API_KEY")) and (os.getenv("LLM_MODEL") or os.getenv("CLOUDRU_MODEL"))),
            "model": os.getenv("LLM_MODEL") or os.getenv("CLOUDRU_MODEL") or None}


async def complete(skill, payload):
    if os.getenv("LLM_BASE_URL"):
        from .models import compatible
        return await compatible(os.environ["LLM_BASE_URL"],os.getenv("LLM_API_KEY") or os.getenv("CLOUDRU_API_KEY", ""),
                                os.getenv("LLM_MODEL") or os.getenv("CLOUDRU_MODEL", ""),skill,payload,
                                allow_private=os.getenv('SYSTEM_LLM_ALLOW_PRIVATE_NETWORK')=='1',json_mode=True)
    if not status()["configured"]:
        raise ValueError("Настройте CLOUDRU_API_KEY и CLOUDRU_MODEL в локальном .env")
    async with httpx.AsyncClient(timeout=150, follow_redirects=False) as client:
        response = await client.post(ENDPOINT + "/chat/completions", headers={
            "Authorization": "Bearer " + os.environ["CLOUDRU_API_KEY"]}, json={
                "model": os.environ["CLOUDRU_MODEL"], "temperature": .2,
                "messages": [{"role": "system", "content": skill},
                             {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]})
        if not response.is_success:
            raise ValueError(f"Cloud.ru вернул HTTP {response.status_code}. Проверьте доступы и квоты.")
        data = response.json()
    metadata=reply_metadata(data,os.environ['CLOUDRU_MODEL'])
    choice = data.get("choices", [{}])[0]
    if choice.get("finish_reason") == "length":
        raise with_usage(ValueError("Ответ модели обрезан лимитом токенов. Уменьшите модуль."),metadata)
    raw = choice.get("message", {}).get("content", "")
    try:
        value = json.loads(re.sub(r"\s*```\s*$", "", re.sub(r"^\s*```(?:json)?\s*", "", raw)))
    except (TypeError, ValueError):
        raise with_usage(ValueError("Модель вернула некорректный JSON"),metadata) from None
    return {"value":value,**metadata}
