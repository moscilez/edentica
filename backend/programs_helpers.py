import re
from fastapi import HTTPException


def ensure(condition, message, code=422):
    if not condition:
        raise HTTPException(code, message)


def required(value, maximum=200):
    ensure(isinstance(value, str) and 0 < len(value.strip()) <= maximum
           and not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", value), "Проверьте заполнение полей")
    return value.strip()
