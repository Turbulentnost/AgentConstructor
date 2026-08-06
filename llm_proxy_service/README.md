# LLM Proxy Service

Асинхронный FastAPI-сервис, который выступает единым OpenAI-compatible шлюзом к LLM.

## Зачем

На части ПК LLM доступна только через VPN, но с включённым VPN не работает почта.
Решение: развернуть этот сервис на машине с VPN (IP `192.168.2.135`), а остальные
ПК направляют LLM-запросы на него. Сервис сам последовательно пробует upstream-LLM
и возвращает первый успешный ответ.

Порядок fallback (по умолчанию):

1. **Chat-GPT 5.5** (OpenAI, через ваш `OPENAI_API_KEY`)
2. **Claude** (Anthropic, через `CLAUDE_API_KEY`, модели подтягиваются автоматически)
3. **LM Studio** (`openai/gpt-oss-120b`)

Порядок и параметры backend-ов настраиваются через переменные окружения — код менять не нужно.

## Установка

```bash
pip install -r llm_proxy_service/requirements.txt
```

## Настройка

Скопируйте `llm_proxy_service/.env.example` в `llm_proxy_service/.env` и заполните
ключи и модели. Ключевые переменные:

- `LLM_PROXY_HOST` / `LLM_PROXY_PORT` — где слушать (по умолчанию `0.0.0.0:8080`).
- `LLM_PROXY_CHAIN` — порядок backend-ов, по умолчанию `chatgpt,claude,lmstudio`.
- `LLM_PROXY_<NAME>_BASE_URL` / `_MODEL` / `_API_KEY` / `_API_KEY_ENV` / `_STYLE` / `_TIMEOUT_SECONDS`.
  - `_STYLE`: `openai` (chat/completions) или `anthropic` (messages).
- `LLM_PROXY_<NAME>_DISPLAY_NAME` — человекочитаемое имя модели для UI.
- `LLM_PROXY_<NAME>_SUPPORTS_REASONING=true` — добавить в `/v1/models`
  selectable-варианты `<name>:internal` и `<name>:reason`.
- `CLAUDE_API_KEY` — ключ Anthropic Claude. По умолчанию backend `claude`
  использует именно его и запрашивает список доступных Claude-моделей через
  Anthropic `/v1/models`.
- `ANTHROPIC_BASE_URL` — base URL Claude-compatible API. По умолчанию
  `https://api.claudehub.fun`.
- `LLM_PROXY_CLAUDE_MODELS` — fallback-список Claude-моделей через запятую, если
  Anthropic `/v1/models` возвращает `403 Request not allowed`. Например:
  `claude-sonnet-4-6,claude-opus-4-1`.

> Модель `chatgpt` по умолчанию (`gpt-5.5`) нужно привести
> к реально доступным в вашем OpenAI-аккаунте.

## Запуск (на машине с VPN, IP 192.168.2.135)

```bash
python -m llm_proxy_service
```

Проверка:

```bash
curl http://192.168.2.135:8080/health
```

## API

- `POST /v1/chat/completions` — OpenAI-compatible chat completions. Ответ всегда в
  OpenAI-формате (`choices[0].message.content`), независимо от сработавшего backend-а.
- `GET /v1/models` — список моделей для селекта в OpenAI-compatible чате.
  По умолчанию возвращает `chatgpt`, все доступные Claude-модели из
  Anthropic `/v1/models` (или `LLM_PROXY_CLAUDE_MODELS`, если листинг запрещён),
  и `lmstudio`; для reasoning-моделей дополнительно возвращает
  `<model>:internal` и `<model>:reason`.
- `GET /health` — статус и текущая цепочка backend-ов.

## Пользователи (1С → Postgres + MinIO)

При настройке `DATABASE_URL`, `DB_SERVER`/`DB_NAME` и `JWT_SECRET`:

- синхронизация пользователей из `v8users` (erp_pm) **в Postgres**:
  - при старте (`USER_SYNC_ON_STARTUP=true`);
  - ежедневно по cron `USER_SYNC_CRON` (по умолчанию `0 3 * * *` = 03:00) через
    **APScheduler** внутри процесса прокси — отдельный Celery/Redis не нужен;
- каталог для экрана входа: `GET /v1/auth/users`;
- логин по хэшу пароля 1С (`POST /v1/auth/login`) против локальной копии `password_data`;
- профиль: email и круглая аватарка (`/v1/auth/me`, `/v1/auth/me/avatar`);
- ФИО и подразделение из 1С, пользователем не меняются;
- ручной sync: `POST /v1/admin/users/sync` с заголовком `X-Admin-Token`;
- статус последней синхронизации: поле `user_sync` в `GET /health`.

Для доступа к SQL Server 1С либо Windows-login текущей учётки должен быть
разрешён на `erp_pm`, либо в `.env` задайте `TrustedConnection=no` и
`DB_USER`/`DB_PASSWORD` (SQL-логин с `db_datareader`).

См. переменные в `.env.example` (`DATABASE_URL`, `JWT_*`, `ADMIN_TOKEN`, `DB_*`, `MINIO_*`, `USER_SYNC_*`).

## Изображения агентов (MinIO)

При настройке `MINIO_*` в `.env` прокси сохраняет аватары агентов в MinIO:

- `POST /v1/agents/{agent_id}/image` — multipart upload (`file`)
- `GET /v1/agents/{agent_id}/image` — отдать сохранённое изображение

Ответ upload:

```json
{"agent_id": "...", "image_url": "http://host:8080/v1/agents/.../image"}
```

Desktop-приложение использует `llm_proxy_url` для загрузки аватара на этапе
«Параметры агента».

## Подключение приложения

В `data/settings.json` укажите:

```json
"llm_proxy_url": "http://192.168.2.135:8080"
```

При заданном `llm_proxy_url` приложение отправляет все LLM-запросы на прокси
(OpenAI-compatible), а не напрямую к LLM. Ключи LLM хранятся только на прокси-машине.
