import json
import os
import re
import httpx

ENDPOINT = "https://foundation-models.api.cloud.ru/v1"


def status():
    return {"provider": "Cloud.ru Evolution Foundation Models", "endpoint": ENDPOINT,
            "configured": bool(os.getenv("CLOUDRU_API_KEY") and os.getenv("CLOUDRU_MODEL")),
            "model": os.getenv("CLOUDRU_MODEL") or None}


async def complete(skill, payload):
    if not status()["configured"]:
        raise ValueError("Настройте CLOUDRU_API_KEY и CLOUDRU_MODEL в локальном .env")
    async with httpx.AsyncClient(timeout=150, follow_redirects=False) as client:
        response = await client.post(ENDPOINT + "/chat/completions", headers={
            "Authorization": "Bearer " + os.environ["CLOUDRU_API_KEY"]}, json={
                "model": os.environ["CLOUDRU_MODEL"], "temperature": .2, "max_completion_tokens": 12000,
                "messages": [{"role": "system", "content": skill},
                             {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]})
        if not response.is_success:
            raise ValueError(f"Cloud.ru вернул HTTP {response.status_code}. Проверьте доступы и квоты.")
        data = response.json()
    choice = data.get("choices", [{}])[0]
    if choice.get("finish_reason") == "length":
        raise ValueError("Ответ модели обрезан лимитом токенов. Уменьшите модуль.")
    raw = choice.get("message", {}).get("content", "")
    try:
        value = json.loads(re.sub(r"\s*```\s*$", "", re.sub(r"^\s*```(?:json)?\s*", "", raw)))
    except (TypeError, ValueError):
        raise ValueError("Модель вернула некорректный JSON") from None
    return {"value": value, "usage": {"inputTokens": data.get("usage", {}).get("prompt_tokens", 0),
                                      "outputTokens": data.get("usage", {}).get("completion_tokens", 0)},
            "model": data.get("model", os.getenv("CLOUDRU_MODEL"))}
