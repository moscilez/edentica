# Единый API агента

API обслуживает Python/FastAPI, данные хранятся в PostgreSQL. `GET /api/health` возвращает `backend: "python"` и `database: "postgresql"`. Несовпадение версии при правке или согласовании возвращает HTTP 409. Пользовательский контракт `/api/agent` сохранён.

В статусе провайдера `localTesting: true` и `foreignProvidersEnabled: true` обозначают временный локальный Codex-режим с подпиской ChatGPT. Он недоступен при EDENTICA_MODE=hackathon. `configured` проверяет вход CLI, но доступность лимита подтверждается только реальным запросом. Поля `usage.provider`, `usage.localTesting` и `usage.byProvider` разделяют тестовый расход OpenAI и токены Cloud.ru.

Все операции нового агента доступны через `POST /api/agent`. Ответ JSON, кроме бинарного экспорта. Аутентификация — обычная сессия Edentica; `GET /api/agent` возвращает конфигурационный статус. Для POST передавайте `Content-Type: application/json` и `X-Edentica: 1`. При браузерном Origin он должен совпадать с адресом сервера. Host должен входить в ALLOWED_HOSTS или PUBLIC_URL. Сервер не открывает CORS.

Для стенда проверки сначала зарегистрируйте пользователя или войдите через POST /api/auth/register или /api/auth/login и сохраните cookie session. Пример регистрации: `{"name":"Методист","email":"methodist@example.test","password":"ваш_пароль_не_короче_10_знаков"}`. Это общий механизм авторизации, а не навык агента.

| action | Поля JSON | Результат |
|---|---|---|
| status | — | Провайдер, наличие настроек, доступность PPTX |
| list | — | Программы текущего пользователя |
| delete | id, confirm: true | Удаляет свою программу с материалами и историей; активная задача сначала отменяется. Референсы в библиотеке сохраняются. |
| create | request, referenceIds? | Сохранённый запрос, id программы |
| demo | — | Явно обозначенный подготовленный пример |
| get | id | Полный JSON, job, report, события |
| analyze | id, answers? | Запускает фоновый разбор или уточнение |
| skeleton | id | Запускает построение и проверку каркаса |
| edit_skeleton | id, skeleton, expectedRevision | Проверяет каркас, сохраняет версию, снимает согласование |
| approve | id, confirm:true, expectedRevision | Фиксирует человеческое согласование текущего каркаса |
| generate | id | После approve запускает материалы, продолжает готовые модули |
| revise_module | id, moduleId, instruction | Меняет только выбранный модуль |
| cancel | id | Отмена выполняющейся задачи |
| validate | id | Актуальный отчёт структуры, покрытия, источников |
| check_sources | id | Запускает проверку доступности URL по allowlist |
| verify_source | id, sourceId, status, evidence | Ручное подтверждение или отклонение; evidence начинается с HTTPS первоисточника |
| restore | id, revision | Восстановление версии без прежнего согласования |
| export | id, format, moduleId? | DOCX, PPTX, GIFT или JSON; moduleId ограничивает PPTX одним модулем |

Фоновые операции немедленно возвращают программу с `job.state=running`. Опрашивайте get не чаще раза в две секунды. Состояния job: running, completed, failed, cancelled, interrupted. Ошибка находится в job.error. Отсутствие настроек, запрет запуска до согласования, неверные часы и устаревшая версия возвращают 422. Доступ без сессии — 401. Чужой id не раскрывает содержимое.

Ожидаемая последовательность:

```json
{"action":"create","request":"Программа повышения квалификации на 72 часа по Python для аналитиков банков без опыта программирования. Очно-заочно, 4 недели. Итог — защита проекта."}
```

```json
{"action":"analyze","id":"ID_ПРОГРАММЫ"}
```

После ответов на вопросы и состояния ready_for_skeleton:

```json
{"action":"skeleton","id":"ID_ПРОГРАММЫ"}
```

Методист читает каркас из get, при необходимости правит его, затем подтверждает текущую revision:

```json
{"action":"approve","id":"ID_ПРОГРАММЫ","confirm":true,"expectedRevision":2}
```

```json
{"action":"generate","id":"ID_ПРОГРАММЫ"}
```

Программа в JSON содержит request, requirements, questions, skeleton, materials (по moduleId), sections, finalAssessment, sources, approval, usage, history и job. Ответ get дополнен report с errors, warnings и coverage. В report.passed отражены структурные проверки, а не экспертное утверждение. Источники, не подтверждённые человеком, остаются предупреждениями и маркируются в DOCX.

Схема каркаса: темы имеют hours с полями lecture/practice/lab/self; их сумма равна totalHours темы. delivery.inPerson + delivery.remote равно контактным часам lecture+practice+lab. В selfStudyOnly контактные виды равны нулю. Сумма модулей + finalHours равна totalHours программы. Календарь содержит weeks и sessions: каждая строка ссылается ровно на одну тему через topicIds; для итоговой аттестации используется `final`. Часы календаря сверяются с каждой темой отдельно.

Импорт референса использует существующий `POST /api/materials` с `{"name":"reference.docx","data":"BASE64"}`. Возвращённый id передаётся в referenceIds при create. Ограничение файла — 5 МБ, извлечённого текста — 50 000 знаков; агенту передаются первые 22 000 знаков каждого референса. Усечённый импорт помечается в интерфейсе. Файлы с внешними XML-сущностями и превышением лимитов архива отклоняются.
