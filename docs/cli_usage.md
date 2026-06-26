# CLI для проверки ядра AgentConstructor

CLI нужен для проверки ядра системы без desktop UI. Он не запускает PySide6, не
поднимает web-сервер, не использует Redis/Celery и не выполняет опасные Outlook
действия.

## Создать AgentSpec

```bash
python scripts/run_agent_cli.py build-agent "Создай агента, который проверяет Outlook и находит поручения"
```

Команда создаёт `AgentBuilder`, строит `AgentSpec` и печатает цель, требования
к данным, разрешённые инструменты, граф и runtime limits. Инструменты не
вызываются, COM не используется.

## Запустить на fake tools

```bash
python scripts/run_agent_cli.py run-fake "Создай агента, который проверяет Outlook и находит поручения"
```

`run-fake` — безопасная проверка без Outlook. Команда регистрирует fake tools:

- `outlook.search_mail`
- `outlook.read_calendar`
- `outlook.read_tasks`
- `report.build_task_report`
- `email.create_draft`
- `email.send`

Ожидаемый результат для агента контроля поручений — статус `completed` и
локальный fake-отчёт.

## Диагностика Outlook COM

```bash
python scripts/run_agent_cli.py diagnose-outlook
```

`diagnose-outlook` запускает только `SubprocessComWorker` с
`tool_name="outlook.diagnostics"`. Команда не создаёт `AgentBuilder` и не
запускает runtime. Если Outlook COM/MAPI зависает, CLI печатает `WORKER_TIMEOUT`
и последний доступный диагностический шаг.

## Запустить на Outlook read-only tools

```bash
python scripts/run_agent_cli.py run-outlook-readonly "Создай агента, который проверяет Outlook и находит поручения"
```

`run-outlook-readonly` запускает агента через Runtime и ToolGateway, но Outlook
действия выполняются только через безопасный `SubprocessComWorker`.

Регистрируются COM-backed tools:

- `outlook.search_mail`
- `outlook.read_calendar`
- `outlook.read_tasks`
- `email.create_draft`
- `email.send`

`report.build_task_report` регистрируется как local fake tool, потому что
формирование отчёта не требует COM.

Обычные ошибки внешней интеграции не считаются падением CLI:

- `WORKER_TIMEOUT`
- `COM_NOT_AVAILABLE`
- `OUTLOOK_ACCESS_ERROR`
- `OUTLOOK_COM_ERROR`
- `OUTLOOK_TOOL_NOT_IMPLEMENTED`
- `UNKNOWN_COM_TOOL`

`outlook.read_tasks` может вернуть `OUTLOOK_TOOL_NOT_IMPLEMENTED`, потому что
реальный COM worker для задач пока не реализован.

## Проверить блокировку отправки

```bash
python scripts/run_agent_cli.py test-send-block
```

`test-send-block` проверяет два уровня защиты:

1. `ToolGateway` блокирует `email.send` без `human_approved=True` и возвращает
   `HUMAN_APPROVAL_REQUIRED`.
2. Даже с `human_approved=True` Outlook worker safe mode возвращает
   `SEND_DISABLED_FOR_SAFETY`.

Ожидаемый итог:

```text
gateway_without_approval: HUMAN_APPROVAL_REQUIRED
gateway_with_approval: SEND_DISABLED_FOR_SAFETY
real_send_executed: false
```

