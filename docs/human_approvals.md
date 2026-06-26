# Очередь подтверждений человека

`HumanApproval` — это запрос к пользователю, который создаётся, когда агент не
может безопасно продолжить выполнение автоматически. Например, runtime может
остановиться перед write/dangerous-инструментом или на узле ручной проверки.

## Когда агент останавливается

Если Runtime вызывает `state.pause_for_human(...)`, запуск получает статус
`paused_for_human`. В `AgentRuntimeState` всё ещё хранится
`pending_human_approval`, чтобы запуск можно было восстановить и продолжить.

Дополнительно создаётся отдельная запись `HumanApprovalRecord` в таблице
`human_approval_requests`. Эта таблица нужна для очереди UI/CLI: можно быстро
получить все pending-запросы, открыть конкретный запрос и увидеть историю
решений.

## Где хранится pending approval

Pending approval хранится в двух местах с разными задачами:

- `AgentRuntimeState.pending_human_approval` — runtime-снимок для `resume`.
- `human_approval_requests` — индексируемая очередь и история решений человека.

## CLI

Показать очередь ожидающих подтверждений:

```bash
python scripts/run_agent_cli.py list-approvals
```

Показать конкретное подтверждение:

```bash
python scripts/run_agent_cli.py show-approval <approval_id>
```

Подтвердить и продолжить запуск:

```bash
python scripts/run_agent_cli.py approve <approval_id>
```

Отклонить и продолжить запуск по ветке отказа:

```bash
python scripts/run_agent_cli.py reject <approval_id> "Причина"
```

## Safe Mode

Подтверждение человека не обходит `ToolGateway`, permissions и safe mode
инструментов. Оно только разрешает Runtime продолжить выполнение того места, где
агент остановился.

Даже если пользователь подтвердит действие `email.send`, реальная отправка не
произойдёт: `OutlookComWorker` по-прежнему блокирует отправку через
`SEND_DISABLED_FOR_SAFETY`.

