# Docker: локально, ВМ и VPS

Требуются Docker Engine и Docker Compose plugin. Отдельная установка Python, Node.js, PostgreSQL или npm build на сервер не нужна.

## Сервисы

- frontend — непривилегированный Nginx, порт 8000; статические файлы и reverse proxy /api.
- backend — Python/FastAPI, внутренний порт 3000; Node используется для существующих правил.
- db — PostgreSQL 18, только внутренняя сеть.
- test и test-db — изолированный профиль проверок; production volume и реальные ключи в тесты не передаются.

Образы приложения не содержат .env, пользовательских данных, локальных Python-окружений и артефактов. Frontend копирует только рабочие файлы интерфейса.

## Подготовка окружения

Скопируйте исходники на сервер без .env, .env.docker, data, output, .venv, node_modules и .git.
В каталоге проекта:

```bash
cp .env.docker.example .env.docker
chmod 600 .env.docker
```

Укажите длинный случайный POSTGRES_PASSWORD из букв/цифр (например результат `openssl rand -hex 32`).
Для APP_ENCRYPTION_KEY нужен URL-safe base64 ключ на 32 байта (`openssl rand -base64 32 | tr '+/' '-_'`).
При наличии Python можно выполнить `python scripts/docker-init.py`: он создаёт оба ключа и не перезаписывает существующий файл.

Локальные значения:

```dotenv
PUBLIC_URL=http://localhost:8000
BIND_ADDRESS=127.0.0.1
HTTP_PORT=8000
COOKIE_SECURE=0
```

На публичной ВМ/VPS нужен HTTPS: настройте домен/сертификат и reverse proxy либо используйте выданный HTTPS demo URL.
Публичный HTTP для паролей и персональных API-ключей не поддерживается; backend откажется запускаться с внешним HTTP PUBLIC_URL.

```dotenv
PUBLIC_URL=https://your-domain.example
COOKIE_SECURE=1
BIND_ADDRESS=127.0.0.1
HTTP_PORT=8000
```

Если перед ВМ уже стоит HTTPS-прокси инфраструктуры и он должен подключаться к внешнему порту ВМ, задайте BIND_ADDRESS=0.0.0.0 и ограничьте доступ сетевыми правилами провайдера. Приложение на ВМ слушает 0.0.0.0:8000. Не включайте HTTP-доступ к реальным паролям/ключам как промежуточный способ настройки.

Модель сервера:

```dotenv
LLM_BASE_URL=https://hub.gigaschool.ru/api/v1/llm/v1
LLM_API_KEY=your-issued-key
LLM_MODEL=GigaChat/GigaChat-3-Pro
```

Для Cloud.ru Evolution используйте CLOUDRU_API_KEY и CLOUDRU_MODEL (адрес https://foundation-models.api.cloud.ru/v1). Алиасы OPENAI_BASE_URL/OPENAI_API_KEY/OPENAI_MODEL означают совместимый протокол, а не разрешение API OpenAI. Приоритет: LLM_* → OPENAI_* → CLOUDRU_*. Не смешивайте настройки разных провайдеров. Точный контракт: [workflow.md](workflow.md#конфигурация). В текущем развёртывании по указанию владельца SYSTEM_LLM_SHARED_ACCESS=1: серверная модель доступна всем зарегистрированным методистам, ключ остаётся на сервере. Внутренних токенных бюджетов нет; квоты поставщика сохраняются. Для ограничения доступа отключите этот флаг и укажите SYSTEM_LLM_ALLOWED_USERS=uuid1,uuid2 либо используйте личные подключения. Пользовательские подключения к разрешённым в режиме хакатона моделям добавляются через настройки профиля и шифруются APP_ENCRYPTION_KEY. Сохраняйте этот ключ неизменным между релизами.
Локальный Codex CLI через ChatGPT работает только в локальном Python-сервере на loopback; Windows-авторизация Codex не копируется на публичную ВМ.

## Сборка и запуск

```bash
docker compose --env-file .env.docker config --quiet
docker compose --env-file .env.docker build
docker compose --env-file .env.docker up -d --wait
docker compose --env-file .env.docker exec -T backend python -m backend.preflight
docker compose --env-file .env.docker ps
curl -f http://127.0.0.1:8000/api/health
docker compose --env-file .env.docker logs --tail=100 backend frontend
```

Откройте PUBLIC_URL, создайте аккаунт с нужной ролью. База изначально пустая, без кейсовых примеров.
Без ключа модели работают аккаунты и сценарии каталога/обучения, генерация недоступна.
Health проверяет доступность приложения и БД, а не качество материалов или подключение LLM.

```bash
# Тесты без платных модельных вызовов и без production volume
docker compose --env-file .env.docker --profile test build test
docker compose --env-file .env.docker --profile test run --rm test
# Удалить остановленный тестовый сервер; его данные находятся в tmpfs
docker compose --env-file .env.docker --profile test stop test-db
```

TestClient использует локальный HTTP внутри контейнера, поэтому тестовый сервис отдельно задаёт COOKIE_SECURE=0. На публичный backend это не распространяется.

## Постоянные данные

Volume edentica-postgres хранит PostgreSQL; edentica-data — файлы приложения. Таблицы обновляются при старте backend. Запускайте один backend: текущий планировщик не рассчитан на горизонтальное масштабирование.

```bash
docker compose --env-file .env.docker down
docker compose --env-file .env.docker up -d --wait
# После обновления файлов:
docker compose --env-file .env.docker build
docker compose --env-file .env.docker up -d --wait
```

Не добавляйте -v к down: это удаляет тома. После инициализации PostgreSQL изменение POSTGRES_PASSWORD только в файле не меняет пароль в БД. Новому релизу нужны прежние POSTGRES_PASSWORD и APP_ENCRYPTION_KEY.

## Nginx/Caddy перед контейнером

Если TLS завершает прокси хоста, передавайте исходный Host, сохраняйте cookie и разрешите запросы до 7 МБ:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $http_host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 7m;
    proxy_read_timeout 180s;
}
```

Это location-фрагмент; сертификат и server-блок настраиваются отдельно. API-лимиты авторизованных запросов считаются по пользователю. Лимит входа/регистрации остаётся на IP непосредственного прокси; для большого потока регистраций нужен отдельно доверенный механизм клиентских IP и инфраструктурная защита.

## Резервные копии

Копируйте бинарные дампы через docker cp, чтобы PowerShell не изменил байты:

```bash
docker compose --env-file .env.docker exec -T db pg_dump -U edentica -d edentica -Fc -f /tmp/edentica.dump
docker compose --env-file .env.docker exec -T db pg_restore --list /tmp/edentica.dump
docker compose --env-file .env.docker cp db:/tmp/edentica.dump ./edentica.dump
```

Отдельно сохраните APP_ENCRYPTION_KEY и файлы edentica-data. Без ключа подключения моделей не расшифровать.
Для согласованной копии файлов остановите backend. Восстановление делайте в новую пустую БД при остановленном backend:

```bash
docker compose --env-file .env.docker stop backend
docker compose --env-file .env.docker cp ./edentica.dump db:/tmp/restore.dump
docker compose --env-file .env.docker exec -T db pg_restore -U edentica -d edentica --no-owner --no-acl --exit-on-error /tmp/restore.dump
docker compose --env-file .env.docker up -d --wait
```

Не восстанавливайте поверх рабочей БД без резервной копии. Физический Windows-каталог data/postgres не переносится в Linux: используйте pg_dump. Файлы приложения восстанавливаются с UID/GID 10001.

## ВМ команды

Код загружается отдельным релизом внутри ~/project/edentica-release-*, без Git-операций. Docker Compose работает из этого каталога. Актуальный путь записан локально в data/vm-release.json; это служебная метаинформация, не пароль.

Серверные секреты хранятся вне репозитория в ~/.config/edentica/runtime.env (права 600), в каталог релиза копируется .env.docker. Ключ LLM читается на самой ВМ из /opt/hackathon/ai.env; он не входит в архив исходников и не выводится в журнал.

Официальные справки: [Compose profiles](https://docs.docker.com/reference/compose-file/profiles/), [установка Compose](https://docs.docker.com/compose/install/), [образ PostgreSQL](https://hub.docker.com/_/postgres).
