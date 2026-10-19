"""Run before serving or judging: python -m backend.preflight. Never prints keys."""
import json
import os
from .config import Settings


def main():
    try:
        cfg=Settings.load().validate()
        result={'mode':cfg.mode,'provider':cfg.provider,'endpoint':cfg.base_url,'model':cfg.model,
                'keyConfigured':bool(cfg.api_key),'databaseConfigured':bool(os.getenv('DATABASE_URL')),
                'encryptionConfigured':bool(os.getenv('APP_ENCRYPTION_KEY')),'workflowVersion':2}
        result['ready']=all(result[k] for k in ('keyConfigured','databaseConfigured','encryptionConfigured')) or cfg.provider=='codex' and cfg.mode=='local'
        print(json.dumps(result,ensure_ascii=False));return 0 if result['ready'] else 2
    except ValueError as error:
        print(json.dumps({'ready':False,'error':str(error)},ensure_ascii=False));return 2


if __name__=='__main__':raise SystemExit(main())
