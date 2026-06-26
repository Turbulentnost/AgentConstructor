# AgentApplicationService

`AgentApplicationService` — сервисный слой приложения для операций с агентами.
Он нужен, чтобы будущий desktop UI не собирал и не вызывал напрямую низкоуровневые
компоненты.

UI не должен напрямую работать с:

- `AgentBuilder`;
- `ToolGateway`;
- `SimpleAgentRuntime`;
- storage repositories;
- COM worker.

Вместо этого UI должен получать `AgentApplicationService` из
`ApplicationContainer` и вызывать методы сервиса.

## Зачем нужен сервис

Сервис фиксирует границы приложения:

- построение preview-агента;
- сохранение агента;
- запуск сохранённого агента;
- запуск временного `AgentSpec`;
- продолжение запуска после HumanApproval;
- audit событий;
- memory-only режим для CLI и тестов.

Так UI остаётся тонким слоем отображения и не получает доступ к ToolGateway или
COM worker напрямую.

## Методы

### `build_preview(user_request)`

Строит `AgentSpec` из пользовательского запроса, но не сохраняет и не запускает
его. Подходит для preview-экрана конструктора.

### `create_agent_from_request(user_request, save=True)`

Строит `AgentSpec` и при необходимости сохраняет. Если `save=False`, агент
создаётся временно, например для CLI smoke-запуска.

### `save_agent(agent_spec)`

Сохраняет агента в repository или memory-only storage. Добавляет audit action
`agent.saved`.

### `get_agent(agent_id)` и `list_agents()`

Возвращают сохранённых агентов из repository или memory-only storage.

### `run_agent(agent_id, initial_variables=None)`

Берёт сохранённый агент и запускает его через уже переданный в сервис runtime.
Сервис не собирает runtime внутри метода.

### `run_agent_spec(agent_spec, initial_variables=None)`

Запускает временный `AgentSpec` без сохранения. Используется CLI и unit-тестами.

### `resume_run(agent_spec, state, approved, comment=None)`

Продолжает запуск после HumanApproval и пишет audit action:

- `human.approval_approved`;
- `human.approval_rejected`.

## Memory-only режим

Если repositories не переданы, сервис хранит агентов в памяти:

```python
self._memory_agents: dict[str, AgentSpec]
```

Это нужно для CLI, unit-тестов и раннего MVP. Memory-only режим не заменяет
SQLite storage, но позволяет развивать UI и сервисный слой независимо.

Audit events в этом режиме сохраняются в `memory_audit_logs`.

## Использование в будущем UI

PySide6 UI должен получать сервис из container:

```python
container = build_application_container(config)
service = container.agent_service
```

UI вызывает `service.build_preview(...)`, `service.save_agent(...)`,
`service.run_agent(...)` и `service.resume_run(...)`. Все проверки tools,
HumanApproval и runtime-логика остаются внутри application/core слоёв.

Это сохраняет правило: UI не вызывает COM, не вызывает инструменты и не обходит
`ToolGateway`.

