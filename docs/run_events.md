# Журнал событий запуска агента

`AgentRunEvent` — структурированное событие выполнения агента. Оно фиксирует,
что произошло во время запуска: старт, выполнение узла графа, вызов инструмента,
ожидание подтверждения человека, сохранение checkpoint и финальный статус.

## State и события

`AgentRuntimeState` хранит последний снимок запуска: текущий статус, текущий
узел, переменные, ошибки и результаты инструментов. Это удобно для resume и
быстрого ответа на вопрос "где агент сейчас".

Журнал событий хранит путь агента во времени. Он отвечает на вопросы "какой узел
выполнялся", "какой инструмент вызывался", "где запуск остановился" и "что
случилось перед ошибкой". События не заменяют state, а дополняют его.

## Типы событий

Сохраняются следующие типы событий:

- `run_started`
- `node_started`
- `node_completed`
- `node_failed`
- `tool_call_started`
- `tool_call_completed`
- `tool_call_failed`
- `human_approval_requested`
- `human_approval_answered`
- `run_completed`
- `run_failed`
- `run_cancelled`
- `checkpoint_saved`

## CLI

Посмотреть события запуска можно командой:

```bash
python scripts/run_agent_cli.py show-events <run_id>
```

По умолчанию CLI печатает время, тип события, `node_id`, `tool_name` и сообщение.
Большие `details` не выводятся полностью. Для краткого просмотра деталей можно
использовать:

```bash
python scripts/run_agent_cli.py show-events <run_id> --verbose
```

## Будущий UI

Desktop UI сможет читать `RunEventRepository.list_events(run_id)` и показывать
таймлайн запуска: активный узел, вызванные инструменты, остановки на
HumanApproval, ошибки и checkpoint'ы. Такой экран будет работать поверх SQLite и
не потребует Redis, Celery или прямого доступа к COM.

