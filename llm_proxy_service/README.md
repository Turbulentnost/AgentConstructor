# LLM Proxy Service

Асинхронный FastAPI-сервис, который выступает единым OpenAI-compatible шлюзом к LLM.

## Зачем

На части ПК LLM доступна только через VPN, но с включённым VPN не работает почта.
Решение: развернуть этот сервис на машине с VPN (IP `192.168.2.135`), а остальные
ПК направляют LLM-запросы на него. Сервис сам последовательно пробует upstream-LLM
и возвращает первый успешный ответ.

Порядок fallback (по умолчанию):

1. **Chat-GPT 5.5** (OpenAI, через ваш `OPENAI_API_KEY`)
2. **LM Studio** (`openai/gpt-oss-120b`)

Порядок и параметры backend-ов настраиваются через переменные окружения — код менять не нужно.

## Установка

```bash
pip install -r llm_proxy_service/requirements.txt
```

## Настройка

Скопируйте `llm_proxy_service/.env.example` в `llm_proxy_service/.env` и заполните
ключи и модели. Ключевые переменные:

- `LLM_PROXY_HOST` / `LLM_PROXY_PORT` — где слушать (по умолчанию `0.0.0.0:8080`).
- `LLM_PROXY_CHAIN` — порядок backend-ов, по умолчанию `chatgpt,lmstudio`.
- `LLM_PROXY_<NAME>_BASE_URL` / `_MODEL` / `_API_KEY` / `_API_KEY_ENV` / `_STYLE` / `_TIMEOUT_SECONDS`.
  - `_STYLE`: `openai` (chat/completions) или `anthropic` (messages).
- `LLM_PROXY_<NAME>_DISPLAY_NAME` — человекочитаемое имя модели для UI.
- `LLM_PROXY_<NAME>_SUPPORTS_REASONING=true` — добавить в `/v1/models`
  selectable-варианты `<name>:internal` и `<name>:reason`.

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
  По умолчанию возвращает `chatgpt`, `lmstudio`; для reasoning-моделей
  дополнительно возвращает `<name>:internal` и `<name>:reason`.
- `GET /health` — статус и текущая цепочка backend-ов.

## Подключение приложения

В `data/settings.json` укажите:

```json
"llm_proxy_url": "http://192.168.2.135:8080"
```

При заданном `llm_proxy_url` приложение отправляет все LLM-запросы на прокси
(OpenAI-compatible), а не напрямую к LLM. Ключи LLM хранятся только на прокси-машине.
