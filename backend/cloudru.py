"""Approved system-model transport resolved through the central configuration."""
import os
from .config import Settings


def status():
    cfg=Settings.load()
    return {'provider':'Cloud.ru Evolution Foundation Models' if 'foundation-models.api.cloud.ru' in cfg.base_url else 'Шлюз хакатона',
            'endpoint':cfg.base_url,'configured':bool(cfg.api_key and cfg.model),'model':cfg.model or None,'policy':cfg.mode}


async def complete(skill,payload):
    cfg=Settings.load().validate()
    if not cfg.api_key or not cfg.model:
        raise ValueError('Настройте ключ и модель: CLOUDRU_API_KEY/CLOUDRU_MODEL либо LLM_API_KEY/LLM_MODEL')
    from .models import compatible
    return await compatible(cfg.base_url,cfg.api_key,cfg.model,skill,payload,
        allow_private=os.getenv('SYSTEM_LLM_ALLOW_PRIVATE_NETWORK')=='1',json_mode=True)
