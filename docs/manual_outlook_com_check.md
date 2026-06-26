# Как проверить Outlook COM вручную

1. Откройте проект в Cursor.
2. Убедитесь, что используется Windows.
3. Убедитесь, что установлен Outlook.
4. Откройте Outlook вручную и проверьте, что профиль пользователя настроен.
5. Установите зависимости проекта:

```bash
pip install -e .
```

Если в проекте используется requirements-файл, используйте:

```bash
pip install -r requirements.txt
```

6. Проверьте pywin32:

```bash
python -c "import pythoncom, win32com.client; print('pywin32 OK')"
```

7. Запустите smoke-проверку worker:

```bash
python scripts/smoke_outlook_com_diagnostics.py
python scripts/smoke_outlook_com_read.py
```

8. Запустите smoke-проверку полного пути через ToolGateway:

```bash
python scripts/smoke_outlook_tool_gateway.py
```

## Как понять результат

Если всё работает:

- для писем будет `ok=True` и `count > 0` или `count == 0`, если писем нет;
- для календаря будет `ok=True` и `count >= 0`;
- `email.send` будет заблокирован.

Если COM недоступен:

- будет `COM_NOT_AVAILABLE`;
- это значит, что проверка запущена не на Windows, нет pywin32 или не настроен Outlook.

Если Outlook/MAPI недоступен:

- будет `OUTLOOK_ACCESS_ERROR`;
- Outlook может быть не установлен;
- Outlook мог ни разу не запускаться;
- профиль пользователя может быть не настроен;
- у текущей Windows-сессии может не быть доступа к MAPI.

## Если Outlook COM зависает

`pywin32` может быть доступен, но Outlook COM/MAPI всё равно может зависнуть на
реальном вызове: `Dispatch`, `GetNamespace`, `GetDefaultFolder`, `Items`,
`Sort`, `Count` или чтении первого элемента. Проверка доступности COM не
означает, что MAPI-профиль Outlook готов к работе.

Все реальные Outlook COM-вызовы в ручных smoke-проверках запускаются через
`SubprocessComWorker` в отдельном Python-процессе. Если дочерний процесс
зависает, основной процесс завершает его по timeout и возвращает
`WORKER_TIMEOUT`.

Чтобы понять место зависания, сначала запустите диагностику:

```bash
python scripts/smoke_outlook_com_diagnostics.py
```

Затем запустите чтение:

```bash
python scripts/smoke_outlook_com_read.py
```

В сообщении `WORKER_TIMEOUT` будет последний доступный stderr с шагами
`COM_DIAG`, например `step=dispatch_outlook start` или
`step=get_namespace start`.

Возможные причины зависания:

- Outlook не открыт;
- профиль Outlook не настроен;
- открыто окно входа или запроса пароля;
- открыто модальное окно Outlook;
- корпоративная политика безопасности блокирует MAPI;
- это первый запуск Outlook;
- повреждён профиль MAPI.

## Что запрещено

- Не включать отправку писем.
- Не создавать черновики.
- Не удалять письма.
- Не перемещать письма.
- Не менять события календаря.
- Не запускать эти smoke-проверки как обычные unit-тесты в CI.
