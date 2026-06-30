# LLM Supervised Runtime

## Planner vs Supervisor

LLM Planner участвует до запуска: анализирует запрос пользователя и помогает выбрать
инструменты из `ToolsCatalog`. Он не исполняет tools и не строит доверенный runtime
самостоятельно.

LLM Supervisor участвует во время запуска: после `tool_result` получает состояние
агента, последнее событие, последний результат инструмента и контекст доступных
tools. Его ответ — только `SupervisorDecision`.

## Tool-Event Trigger

Runtime вызывает Supervisor после значимого результата инструмента. Supervisor
может вернуть:

- `continue_to_next`
- `retry_tool`
- `call_additional_tool`
- `ask_human`
- `request_credentials`
- `replan_graph`
- `finish_success`
- `finish_failed`

## Что Получает LLM

Supervisor prompt содержит:

- `AgentSpec`
- текущий `AgentRuntimeState`
- последнее событие запуска
- последний `ToolCallRecord`
- `tools_context` из `ToolsCatalog`
- JSON-схему `SupervisorDecision`

Runtime передаёт tools расширенный контекст: `agent_goal`, `user_request`,
`variables`, `tool_outputs`, `data_requirements` и `runtime_context`.

## Безопасность

LLM не вызывает инструменты напрямую. Все tool calls проходят через Runtime и
`ToolGateway`. `ToolGateway` проверяет `AgentSpec`, регистрацию в `ToolRegistry`,
уровень риска и HumanApproval.

LLM прямо запрещено:

- вызывать COM;
- открывать Outlook, 1С или браузер напрямую;
- писать произвольный Python-код;
- придумывать `tool_name`;
- отправлять письма;
- писать в 1С;
- менять Outlook;
- нажимать подтверждающие кнопки в браузере.

Outlook, 1С и Browser на текущем этапе read-only. `email.send` остаётся dangerous
и в safe mode не должен выполняться без подтверждения.

## Пример: Outlook Schedule Agent

Запрос:

`Нужен агент, который смотрит все совещания в Outlook и выводит как лучше распланировать свой график`

Новый граф:

1. `validate_request`
2. `read_calendar` — `outlook.read_calendar`
3. `analyze_calendar_load` — `llm.analyze_collected_data`
4. `build_schedule_recommendations` — `report.build_schedule_recommendations`
5. `final`

Такой агент не меняет календарь. Он читает события, анализирует нагрузку,
выделяет перегруженные интервалы и формирует рекомендации по свободным окнам и
фокус-времени.

