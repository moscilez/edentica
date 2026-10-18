# Эдентика

Платформа для создания учебных программ методистом, экспертного согласования и прохождения этих учебных программ учениками на самой платформе Эдентика.

Стек: **Python 3.12 / FastAPI / PostgreSQL 18 / JavaScript / Nginx / Docker Compose**.
Сервисы: backend, frontend, db; отдельный профиль test с временной test-db. npm build не требуется.

## Запуск через Docker

1. Создайте `.env.docker` из `.env.docker.example` или выполните `python scripts/docker-init.py`.
2. Заполните APP_ENCRYPTION_KEY и POSTGRES_PASSWORD (скрипт создаёт их автоматически).
3. Для внешнего доступа настройте HTTPS PUBLIC_URL и COOKIE_SECURE=1. Локально — http://localhost:8000.
4. Выполните:

```bash
docker compose --env-file .env.docker build
docker compose --env-file .env.docker up -d --wait
docker compose --env-file .env.docker --profile test run --rm test
```

Полная инструкция: [Docker и ВМ](docs/docker.md).
Роли, создание курсов, экспертиза, группы и ограничения: [Платформа](docs/platform-v2.md).

Модель сервера задаётся CLOUDRU_API_KEY/CLOUDRU_MODEL или LLM_BASE_URL/LLM_API_KEY/LLM_MODEL для OpenAI-совместимого шлюза. Персональные подключения добавляются методистом в профиле.
Локальный Codex через подписку поддерживается отдельно, только на loopback: [инструкция](docs/hackathon/local-openai.md).
Секреты не добавляются в исходники или образ.

Локальная разработка без Docker: [Python и PostgreSQL](docs/hackathon/python-postgres.md).

## Структура

- backend — API, роли, программы, модели, согласование и обучение.
- public — интерфейс; рабочая точка входа program-studio.html, расширение workspace.js.
- deploy — Nginx и образ frontend.
- src/programs — существующие правила/промпты и тестовые фикстуры, вызываемые Python.
- templates — шаблоны АЦР для DOCX.
- tests_python — проверки на изолированных PostgreSQL БД.
- data/output/.venv — локальные данные и артефакты, исключены из образов и Git.

Исходники прежней Node.js LMS сохранены для истории в server.mjs и части src/public; основной сервер их не запускает.
Старая документация выделена в [архив](docs/archive-lms.md) и не является инструкцией развёртывания.

Git-операции выполняет владелец проекта.
