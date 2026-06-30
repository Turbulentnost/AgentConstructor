# Agent Validation

Пробная проверка агента нужна, чтобы понять, может ли `AgentSpec` безопасно
выполниться до сохранения или основного запуска.

## Как Работает Проверка

`AgentValidationService.validate_agent()` выполняет шаги:

1. Проверяет `AgentSpec` через Pydantic.
2. Проверяет tool names через `ToolsCatalog`.
3. Проверяет, что разрешённые tools зарегистрированы в `ToolRegistry`.
4. Запускает пробный runtime с переменными `validation_mode=true` и
   `read_only_trial_run=true`.
5. Возвращает `AgentValidationResult`.

## Статусы

- `not_checked` — проверка ещё не выполнялась.
- `passed` — пробный запуск завершился успешно.
- `failed` — AgentSpec или пробный запуск завершились ошибкой.
- `needs_human` — требуется подтверждение или решение пользователя.
- `needs_credentials` — нужны credentials, но они не передаются через LLM.

## Безопасность Пробного Запуска

Пробный запуск не обходит runtime:

- tools вызываются только через `ToolGateway`;
- dangerous/write действия требуют HumanApproval;
- Outlook, 1С и Browser остаются read-only;
- `email.send` не выполняется автоматически;
- LLM не получает пароли или секреты.

## Если Validation Failed

Нужно посмотреть:

- `errors` в `AgentValidationResult`;
- `warnings`;
- `run_id` и события пробного запуска;
- `suggested_fixes`.

Типичные причины:

- tool есть в `AgentSpec`, но отсутствует в `ToolRegistry`;
- graph node ссылается на незарегистрированный tool;
- runtime остановился на HumanApproval;
- Supervisor запросил credentials.

## UI

На странице создания агента доступны:

- `Предпросмотр`
- `Проверить агента`
- `Сохранить`
- `Собрать, проверить и запустить`
- `Очистить`

UI не управляет tools напрямую. Он вызывает только `AgentApplicationService`,
который делегирует проверку в `AgentValidationService`.

