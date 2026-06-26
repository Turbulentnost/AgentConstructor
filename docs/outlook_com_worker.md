# Outlook COM Worker

`OutlookComWorker` — локальный worker для работы с Outlook через COM в
Windows-сессии пользователя. Он не использует Redis, Celery или серверную
очередь и вызывается только через worker-протокол.

## Safe Mode

Worker работает в `safe_mode=True` по умолчанию. На текущем этапе разрешены
только read-only операции:

- чтение писем из Inbox через `outlook.search_mail`;
- чтение ближайших событий календаря через `outlook.read_calendar`.

Заблокировано:

- отправка писем через `email.send`;
- создание черновиков через `email.create_draft`;
- удаление, перемещение или изменение писем;
- создание и изменение задач;
- создание и изменение календарных событий;
- изменение участников и отправка приглашений;
- любые неизвестные или не реализованные Outlook/email tools.

Даже при `safe_mode=False` реальная отправка писем не реализована. Включать её
можно только после отдельной политики `HumanApproval` и ручного тестирования.

## Ошибки

`OutlookComWorker.execute()` всегда возвращает `WorkerResult` и не выбрасывает
наружу обычные COM-ошибки. Недоступность COM возвращается как
`COM_NOT_AVAILABLE`, ошибки доступа к Outlook/MAPI — как `OUTLOOK_ACCESS_ERROR`,
заблокированные операции — как safety-коды `SEND_DISABLED_FOR_SAFETY`,
`DRAFT_DISABLED_FOR_SAFETY` или `DANGEROUS_ACTION_BLOCKED`.

## Импорт pywin32

`pythoncom` и `win32com.client` импортируются только внутри
`_load_pywin32_modules()` в `agent_desktop_constructor/workers/outlook_com_actions.py`.
Общие слои (`UI`, `AgentBuilder`, `AgentRuntime`, `ToolGateway`, `ToolRegistry`,
`Storage`, `AgentSpec`, `ToolsCatalog`) не импортируют pywin32.

## Тестирование

Unit-тесты не требуют Windows, Outlook или pywin32. Для реальной проверки
`outlook.search_mail` и `outlook.read_calendar` нужен Windows, установленный
Outlook и настроенный профиль пользователя. Ручные smoke-скрипты описаны в
`docs/manual_outlook_com_check.md`.
