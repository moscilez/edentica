"""One configuration contract for model resolution and case restrictions."""
from dataclasses import dataclass
import os
from urllib.parse import urlsplit

APPROVED_ENDPOINTS={('foundation-models.api.cloud.ru','/v1'),('hub.gigaschool.ru','/api/v1/llm/v1')}
APPROVED_MODEL_PREFIXES=('gigachat/','gigachat-','ai-sage/giga','qwen/','qwen2','qwen3','deepseek/','deepseek-')


@dataclass(frozen=True)
class Settings:
    mode:str
    provider:str
    base_url:str
    api_key:str
    model:str

    @classmethod
    def load(cls):
        base=os.getenv('LLM_BASE_URL') or os.getenv('OPENAI_BASE_URL') or 'https://foundation-models.api.cloud.ru/v1'
        key=os.getenv('LLM_API_KEY') or os.getenv('OPENAI_API_KEY') or os.getenv('CLOUDRU_API_KEY','')
        model=os.getenv('LLM_MODEL') or os.getenv('OPENAI_MODEL') or os.getenv('CLOUDRU_MODEL','')
        return cls(os.getenv('EDENTICA_MODE','hackathon'),os.getenv('LLM_PROVIDER','cloudru'),base.rstrip('/'),key,model)

    def validate_endpoint(self,base,model=''):
        if self.mode!='hackathon':return
        u=urlsplit(base)
        if u.scheme!='https' or u.port not in (None,443) or u.username or u.password or u.query or u.fragment or (u.hostname,u.path.rstrip('/')) not in APPROVED_ENDPOINTS:
            raise ValueError('В режиме хакатона доступны только Cloud.ru Evolution и выданный шлюз GIGASCHOOL. Другие API разрешаются только в локальном режиме.')
        if any(x in model.lower() for x in ('gpt-','claude','gemini','openai/','anthropic/','google/')):
            raise ValueError('Эта модель запрещена ограничениями кейса')
        if model and not model.lower().startswith(APPROVED_MODEL_PREFIXES):
            raise ValueError('Модель не входит в разрешённые семейства GigaChat, Qwen и DeepSeek. Администратор должен проверить модель перед добавлением в список.')

    def validate(self):
        if self.mode not in ('local','hackathon'):raise ValueError('EDENTICA_MODE: local или hackathon')
        if self.provider not in ('cloudru','codex'):raise ValueError('LLM_PROVIDER: cloudru или codex')
        if self.provider=='codex' and self.mode!='local':raise ValueError('Codex разрешён только в локальном режиме разработки')
        self.validate_endpoint(self.base_url,self.model)
        return self
