"""Run before serving or judging: python -m backend.preflight. Never prints keys."""
import json
import os
from .config import Settings
from urllib.parse import urlsplit
from cryptography.fernet import Fernet


def main():
    try:
        cfg=Settings.load().validate()
        db_url=urlsplit(os.getenv('DATABASE_URL',''))
        database_valid=db_url.scheme in ('postgresql','postgres') and bool(db_url.hostname and db_url.path.strip('/'))
        try:Fernet(os.getenv('APP_ENCRYPTION_KEY','').encode());encryption_valid=True
        except (ValueError,TypeError):encryption_valid=False
        result={'mode':cfg.mode,'provider':cfg.provider,'endpoint':cfg.base_url,'model':cfg.model,
                'keyConfigured':bool(cfg.api_key),'databaseConfigured':database_valid,
                'encryptionConfigured':encryption_valid,'workflowVersion':3}
        result['ready']=database_valid and encryption_valid and (bool(cfg.api_key and cfg.model) or cfg.provider=='codex' and cfg.mode=='local')
        print(json.dumps(result,ensure_ascii=False));return 0 if result['ready'] else 2
    except ValueError as error:
        print(json.dumps({'ready':False,'error':str(error)},ensure_ascii=False));return 2


if __name__=='__main__':raise SystemExit(main())
