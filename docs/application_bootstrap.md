# Application Bootstrap

`ApplicationContainer` — единая точка сборки зависимостей приложения перед
переходом к desktop UI. UI, CLI и будущий application service должны получать
готовые компоненты из bootstrap-слоя, а не собирать `ToolRegistry`,
`ToolGateway`, `Runtime`, workers и LLM вручную.

## AppConfig

`AppConfig` описывает режим запуска и основные настройки:

- путь к SQLite базе;
- путь к каталогу инструментов;
- включение LLM Planner;
- параметры локальной OpenAI-compatible LLM;
- safe-mode и timeout COM worker-а;
- дефолты чтения Outlook.

`AppConfig.to_llm_config()` преобразует настройки LLM в существующий
`LLMConfig`.

## Run Modes

### fake

Режим по умолчанию. Используются fake-инструменты для разработки, тестов и
демонстрации без Outlook. Внешние системы не нужны.

### outlook_readonly

Регистрируются Outlook COM-backed tools через `SubprocessComWorker`.
Реальные COM-вызовы не происходят при bootstrap-е, а только при последующем
`execute` через worker subprocess.

Разрешённый практический сценарий — read-only:

- `outlook.search_mail`;
- `outlook.read_calendar`.

`email.send` и `email.create_draft` могут присутствовать в registry, но
остаются заблокированными worker-ом и `ToolGateway`/HumanApproval.

### offline

Режим без доступа к COM и внешним системам. Можно использовать локальные
заглушки и LLM Planner, но инструменты не должны обращаться к Outlook.

## Bootstrap

`build_application_container(config)` собирает:

- `AppConfig`;
- `ToolsCatalog`;
- `AgentBuilder`;
- `ToolRegistry`;
- `ToolGateway`;
- `SimpleAgentRuntime`.

Bootstrap не должен:

- запускать агента;
- вызывать инструменты;
- обращаться к COM;
- отправлять письма;
- создавать черновики;
- поднимать UI, web-сервер, Redis или Celery.

## LLM Planner

LLM Planner включается только флагом:

```powershell
$env:AGENT_APP_USE_LLM_PLANNER="true"
```

По умолчанию он отключён. Даже когда он включён, LLM только помогает
планировать: итоговый `AgentSpec` строится кодом `AgentBuilder` и проверяется
через Pydantic + `ToolsCatalog`.

## Outlook Read-only Mode

Пример включения режима Outlook read-only:

```powershell
$env:AGENT_APP_RUN_MODE="outlook_readonly"
$env:AGENT_APP_USE_LLM_PLANNER="false"
```

В этом режиме приложение собирает COM-backed tools, но не вызывает COM во
время bootstrap-а. Outlook будет затронут только при явном runtime-вызове
инструмента через `ToolGateway`.

## Почему UI должен использовать container

Будущий PySide6 UI должен получать зависимости через
`ApplicationContainer`/application service. Это сохраняет единые правила
безопасности:

- один источник `ToolsCatalog`;
- один `ToolGateway`;
- один способ регистрации workers;
- единое управление режимами fake/offline/outlook_readonly;
- отсутствие прямых COM-вызовов в UI.

