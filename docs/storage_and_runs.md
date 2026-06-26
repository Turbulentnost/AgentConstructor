# Storage и Запуски Агентов

Приложение использует локальный SQLite storage для агентов, запусков и истории
состояний. Redis и Celery на MVP не нужны: приложение локальное, COM выполняется
через локальный subprocess worker, а SQLite достаточно для истории и
восстановления состояния.

## Что сохраняется

- `AgentSpec` — созданные спецификации агентов.
- `AgentRun` — записи запусков агентов.
- `AgentRuntimeState` — состояние после шагов runtime.
- `ToolCallLog` — журнал вызовов инструментов, если используется repository.
- `AuditLog` — события приложения: сохранение агента, запуск, checkpoints,
  HumanApproval.

## Где хранится база

По умолчанию:

```text
./data/agents.db
```

Можно переопределить через env:

```powershell
$env:AGENT_APP_DATABASE_PATH="C:\temp\agents.db"
```

## Создать агента

```powershell
python scripts/run_agent_cli.py create-agent "Создай агента, который проверяет Outlook и находит поручения"
```

Команда сохраняет `AgentSpec` в SQLite и печатает `agent_id`.

## Посмотреть агентов

```powershell
python scripts/run_agent_cli.py list-agents
```

Команда только читает SQLite и не вызывает инструменты.

## Запустить агента

```powershell
python scripts/run_agent_cli.py run-agent <agent_id>
```

Runtime создаёт `AgentRun`, сохраняет состояние после шагов и финальный статус.
В режиме `fake` используются fake tools. В режиме `outlook_readonly` Outlook
читается только при runtime-вызове COM-backed tool через `SubprocessComWorker`.

## Посмотреть запуски

```powershell
python scripts/run_agent_cli.py list-runs <agent_id>
```

Команда показывает `run_id`, статус, текущий узел, количество шагов и вызовов
инструментов.

## Посмотреть состояние запуска

```powershell
python scripts/run_agent_cli.py show-run <run_id>
```

Команда показывает сохранённый `AgentRuntimeState`: variables, tool_results,
errors и pending HumanApproval.

## Продолжить после подтверждения

```powershell
python scripts/run_agent_cli.py resume-run <agent_id> <run_id> --approve
```

Или отказать:

```powershell
python scripts/run_agent_cli.py resume-run <agent_id> <run_id> --reject "Причина отказа"
```

Если запуск не находится в `paused_for_human`, CLI выведет понятную ошибку.
Даже после подтверждения dangerous-действий `ToolGateway` и worker safe mode
продолжают блокировать реальную отправку писем.

## Почему Redis пока не нужен

- Приложение локальное и запускается в пользовательской Windows-сессии.
- SQLite хранит агентские спецификации, историю запусков и checkpoints.
- COM выполняется локально через subprocess, без распределённой очереди.
- Redis/Celery добавили бы инфраструктурную сложность без пользы для MVP.

