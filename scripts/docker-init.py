"""Generate a separate Docker configuration without reading local credentials."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parent.parent
target = root / ".env.docker"
if target.exists():
    raise SystemExit(".env.docker уже существует; настройки не изменены.")
example = (root / ".env.docker.example").read_text(encoding="utf-8")
with target.open("x", encoding="utf-8") as stream:
    stream.write(example.replace("REPLACE_WITH_RANDOM_PASSWORD", secrets.token_hex(32)))
try:
    target.chmod(0o600)
except OSError:
    pass
print("Создан .env.docker со случайным паролем БД. Укажите PUBLIC_URL и настройки Cloud.ru.")
