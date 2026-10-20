"""Structured, content-free runtime events and safe correlation IDs."""
import json
import logging
from datetime import datetime,timezone


class JsonFormatter(logging.Formatter):
    def format(self,record):
        value={'time':datetime.now(timezone.utc).isoformat(),'level':record.levelname,'event':record.getMessage()}
        for name in ('jobId','projectId','skill','attempt','status','stage','errorType'):
            if hasattr(record,name):value[name]=getattr(record,name)
        return json.dumps(value,ensure_ascii=False)


def setup():
    log=logging.getLogger('edentica')
    if not log.handlers:
        handler=logging.StreamHandler();handler.setFormatter(JsonFormatter());log.addHandler(handler)
    log.setLevel(logging.INFO);log.propagate=False
    return log


logger=setup()
