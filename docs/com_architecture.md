# COM-архитектура

## Зачем нужен COM

COM нужен для интеграции desktop-приложения с локальными Windows-приложениями:

- Outlook — почта, календарь, задачи.
- Word — чтение и создание документов.
- Excel — чтение и запись таблиц.
- Visio — чтение и экспорт схем.
- 1С — интеграция через `COMConnector`, если API недоступен.
- Другие локальные COM-приложения, доступные в пользовательской Windows-сессии.

## Почему COM нельзя вызывать из UI

COM-вызовы нельзя выполнять из UI, потому что:

- COM может зависнуть.
- Office может открыть модальное окно.
- Outlook, Word или Excel могут быть не установлены.
- COM работает только в Windows-сессии пользователя.
- Зависший COM-вызов не должен ронять всё приложение.

Правило: UI никогда не вызывает COM напрямую.

## Почему нужен отдельный COM Worker

COM Worker нужен, чтобы:

- изолировать COM-вызовы;
- ставить таймауты;
- перезапускать зависший worker;
- возвращать структурированный результат;
- не ломать Runtime и UI при ошибках COM.

## Общая схема

```text
UI -> AgentApplicationService -> AgentRuntime -> ToolGateway -> ComBackedTool -> ComWorker -> pywin32 -> COM-приложение
```

## Где можно импортировать pywin32

Разрешено:

- `agent_desktop_constructor/workers/outlook_com_worker.py`
- `agent_desktop_constructor/workers/word_com_worker.py`
- `agent_desktop_constructor/workers/excel_com_worker.py`
- `agent_desktop_constructor/workers/visio_com_worker.py`
- `agent_desktop_constructor/workers/onec_com_worker.py`
- низкоуровневые модули worker-слоя.

Запрещено:

- UI;
- AgentBuilder;
- AgentRuntime;
- ToolGateway;
- ToolRegistry;
- AgentSpec;
- Storage;
- тесты, которые должны проходить без Windows, Outlook, Word, Excel или 1С.

## Правило безопасной деградации

Если `pywin32` недоступен или система не Windows, COM Worker должен вернуть структурированную ошибку:

```python
{
    "ok": False,
    "error_type": "COM_NOT_AVAILABLE",
    "error_message": "COM доступен только на Windows с установленным pywin32",
}
```

COM Worker не должен выбрасывать `ImportError` наружу.

## Правило отправки писем

`email.send` через COM:

- всегда `dangerous`;
- всегда требует `HumanApproval`;
- на первом этапе реальная отправка должна быть отключена;
- worker должен возвращать `SEND_DISABLED_FOR_SAFETY`.

## Правило работы с утверждёнными документами

Word, Excel и Visio tools могут создавать черновики или читать файлы. Изменение утверждённых документов запрещено без отдельного подтверждения и бизнес-процедуры.
