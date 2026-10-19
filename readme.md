# Эдентика

Платформа для создания учебных программ методистом, экспертного согласования и прохождения этих учебных программ учениками на самой платформе Эдентика.

Стек: **Python 3.12 / FastAPI / PostgreSQL 18 / JavaScript / Nginx / Docker Compose**.
Сервисы: backend, frontend, db; отдельный профиль test с временной test-db. npm build не требуется.

## Запуск через Docker

1. Создайте `.env.docker` из `.env.docker.example` или выполните `python scripts/docker-init.py`.
2. Заполните APP_ENCRYPTION_KEY и POSTGRES_PASSWORD (скрипт создаёт их автоматически).
3. Укажите ключ, точное имя модели и адрес разрешённого шлюза по [контракту конфигурации](docs/workflow.md#конфигурация). Без модели генерация недоступна.
4. Для внешнего доступа настройте HTTPS PUBLIC_URL и COOKIE_SECURE=1. Локально — http://localhost:8000.
5. Выполните:

```bash
docker compose --env-file .env.docker build
docker compose --env-file .env.docker up -d --wait
docker compose --env-file .env.docker exec -T backend python -m backend.preflight
docker compose --env-file .env.docker --profile test build test
docker compose --env-file .env.docker --profile test run --rm test
```

Полная инструкция: [Docker и ВМ](docs/docker.md).
Роли, создание курсов, экспертиза, группы и ограничения: [Платформа](docs/platform-v2.md).

Режим Docker — `hackathon`: разрешены только Cloud.ru Evolution и выданный шлюз GIGASCHOOL, семейства GigaChat, Qwen и DeepSeek. Ограничения применяются и к личным подключениям, включая сохранённые ранее. Произвольные провайдеры и Codex доступны только в отдельном локальном режиме разработки.
Локальный Codex через подписку поддерживается отдельно, только на loopback: [инструкция](docs/hackathon/local-openai.md).
Секреты не добавляются в исходники или образ.

Локальная разработка без Docker: [Python и PostgreSQL](docs/hackathon/python-postgres.md).

## Структура

- backend — API, роли, программы, модели, согласование и обучение.
- public — интерфейс; рабочая точка входа program-studio.html, расширение workspace.js.
- deploy — Nginx и образ frontend.
- backend/resources/skills.json — инструкции навыков и состав двух шаблонов АЦР.
- backend/contracts.py, planning.py, validation.py — типизированный ввод, точное распределение часов, проверки комплекта.
- src/programs — прежняя реализация Node.js; рабочий Python backend её не вызывает.
- templates — шаблоны АЦР для DOCX.
- tests_python — проверки на изолированных PostgreSQL БД.
- data/output/.venv — локальные данные и артефакты, исключены из образов и Git.

Исходники прежней Node.js LMS сохранены для истории в server.mjs и части src/public; основной сервер их не запускает.
Старая документация выделена в [архив](docs/archive-lms.md) и не является инструкцией развёртывания.

## Сквозной сценарий

Запрос и референсы → уточнения только недостающих обязательных полей → каркас с точной арифметикой → **явное утверждение методистом** → материалы по урокам → проверка → черновик комплекта.

Единая точка входа — `POST /api/programs`; `GET /api/programs?id=…` возвращает состояние, прогресс, расход токенов и отчёт. Совместимый `/api/agent` сохранён. Готовые уроки сохраняются для продолжения после отмены или сбоя. Утверждение экспертом и публикация — отдельный этап, структурная проверка его не заменяет.

Выгрузки: DOCX, PPTX, GIFT, JSON, читаемый HTML-отчёт и ZIP всего комплекта. Node.js и npm в серверном Docker-образе не требуются.

[API, конфигурация и воспроизводимая проверка](docs/workflow.md) · [Разбор замечаний оценки](docs/review-20261019.md).

Сетевая доступность источника не подтверждает его содержание или актуальность нормативного документа. Неподтверждённые ссылки и профстандарты явно отмечаются; перед публикацией нужна экспертная проверка.

Git-операции выполняет владелец проекта.
