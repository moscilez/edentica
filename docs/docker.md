# Запуск Эдентики на ВМ/VPS через Docker

На сервере нужны Docker Engine и Compose plugin (команда `docker compose`).
Python, Node.js и PostgreSQL на сам сервер устанавливать не требуется: они находятся в образах.
Используются Linux-контейнеры; на Windows нужен запущенный Docker Desktop в режиме Linux containers.

## Подготовка

Скопируйте исходники проекта на сервер, например в `/opt/edentica`, без `.env`, `node_modules`, `.venv`, `data`, `output` и `.git`.
Нужны Dockerfile, compose.yaml, requirements*.txt, package.json и каталоги backend, public, src, scripts, templates.
Локальный кластер PostgreSQL и данные с компьютера автоматически не переносятся.

```bash
cd /opt/edentica
cp .env.docker.example .env.docker
chmod 600 .env.docker
```

В `.env.docker` замените `POSTGRES_PASSWORD` длинным случайным паролем из букв/цифр (можно получить `openssl rand -hex 32`).
Пароль входит в URL подключения: не используйте `@`, `:`, `/`, `%`, `#`, `$` и другие спецсимволы.
Альтернатива при наличии Python: `python scripts/docker-init.py` создаёт файл и пароль автоматически; существующий файл не перезаписывается.

Параметры для запуска по IP:

```dotenv
POSTGRES_PASSWORD=ваш_случайный_пароль
PUBLIC_URL=http://203.0.113.10:3000
BIND_ADDRESS=0.0.0.0
HTTP_PORT=3000
COOKIE_SECURE=0
CLOUDRU_API_KEY=ваш_ключ
CLOUDRU_MODEL=идентификатор_модели
```

Замените пример IP адресом своего сервера. Разрешите входящий TCP-порт 3000 в firewall ВМ и правилах провайдера.
При PUBLIC_URL с нестандартным портом укажите его и в браузере. ALLOWED_HOSTS нужен только для дополнительных доменов/IP, через запятую, без схемы и портов.
Для тестирования на самом сервере оставьте `BIND_ADDRESS=127.0.0.1` и `PUBLIC_URL=http://localhost:3000`.

## Запуск и проверка

Каждый раз используйте `--env-file .env.docker`: локальный `.env` разработки не предназначен для Docker.

```bash
docker compose --env-file .env.docker config --quiet
docker compose --env-file .env.docker up -d --build --wait
docker compose --env-file .env.docker ps
curl -f http://127.0.0.1:3000/api/health
docker compose --env-file .env.docker logs --tail=100 edentica
```

Откройте адрес из PUBLIC_URL, зарегистрируйте пользователя и откройте демонстрационную программу.
Проверка health должна вернуть `status: ready` и `database: postgresql`.
Проверки здоровья подтверждают доступность приложения и БД, а не качество бизнес-логики или модели.
Без ключа Cloud.ru доступны интерфейс, аккаунты и демонстрация; настоящая генерация требует ключа и модели.

В контейнере принудительно используется провайдер Cloud.ru. Локальный вход по подписке Codex из Windows сюда не переносится.
Node.js используется для существующих правил/промптов; основной сервер работает на Python.
DOCX, JSON, GIFT и PPTX работают без библиотек Codex на сервере: для PPTX предусмотрен переносимый экспорт python-pptx.

## Данные и остановка

PostgreSQL доступен только внутри сети Compose, порт БД на хост не публикуется.
Именованный volume `edentica-postgres` содержит БД PostgreSQL 18; `edentica-data` — файлы приложения и референсы.
Таблицы и миграции создаются приложением при старте после готовности БД.
Запускайте один контейнер приложения: текущий планировщик не рассчитан на горизонтальное масштабирование.

```bash
# Остановка без удаления данных
docker compose --env-file .env.docker down
# Повторный запуск
docker compose --env-file .env.docker up -d --wait
# После изменения исходников или настроек
docker compose --env-file .env.docker up -d --build --wait
```

Не добавляйте `-v` к `down`: этот флаг удаляет тома и данные.
После инициализации БД простая замена POSTGRES_PASSWORD в файле не меняет пароль внутри PostgreSQL: смену нужно согласованно выполнить в БД и конфигурации.

## Домен и HTTPS

Для публичного сервера настройте Nginx/Caddy на хосте с TLS-сертификатом:

```nginx
location / {
    proxy_pass http://127.0.0.1:3000;
    proxy_set_header Host $http_host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 7m;
    proxy_read_timeout 180s;
}
```

Сохранение исходного Host обязательно для проверки разрешённых адресов и Origin.
Укажите `PUBLIC_URL=https://ваш-домен`, `COOKIE_SECURE=1`, `BIND_ADDRESS=127.0.0.1`, затем пересоздайте контейнер приложения.
DNS и выдача сертификата настраиваются отдельно. Конфигурация выше — фрагмент location, а не полный TLS-конфиг.
Приложение пока считает лимиты запросов по адресу proxy: это существующее ограничение для большой аудитории за одним reverse proxy.

## Резервное копирование и перенос

Бинарные дампы переносите через `docker cp`, чтобы перенаправление PowerShell не испортило файл.

```bash
docker compose --env-file .env.docker exec -T postgres pg_dump -U edentica -d edentica -Fc -f /tmp/edentica.dump
docker compose --env-file .env.docker exec -T postgres pg_restore --list /tmp/edentica.dump
docker compose --env-file .env.docker cp postgres:/tmp/edentica.dump ./edentica.dump
```

Для файлов референсов также нужна отдельная копия volume `edentica-data`. Сохраняйте её одновременно с дампом при остановленном приложении.
Для переноса локальной разработки сначала сделайте PostgreSQL-дамп и копию `data` на компьютере; не копируйте каталог физического кластера `data/postgres` в Linux-контейнер.
Восстанавливайте дамп в новую пустую БД, пока приложение остановлено:

```bash
docker compose --env-file .env.docker stop edentica
docker compose --env-file .env.docker cp ./edentica.dump postgres:/tmp/edentica-restore.dump
docker compose --env-file .env.docker exec -T postgres pg_restore -U edentica -d edentica --no-owner --no-acl --exit-on-error /tmp/edentica-restore.dump
docker compose --env-file .env.docker up -d --wait
```

Не выполняйте восстановление поверх рабочей БД без её отдельной резервной копии. Файлы референсов восстанавливаются отдельно с сохранением путей и прав UID/GID 10001.

Официальные справки: [переменные Compose](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/), [образ PostgreSQL и layout данных версии 18](https://hub.docker.com/_/postgres).
