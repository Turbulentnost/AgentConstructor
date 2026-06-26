# Browser, 1C и LLM Analytics Tools

AgentConstructor расширен новыми категориями инструментов: `browser`, `onec` и
`llm_analysis`. Они описаны в `ToolsCatalog` и доступны Builder/LLM Planner для
построения `AgentSpec`.

## Browser Tools

Browser tools нужны, когда агенту требуется актуальная или внешняя информация:
поиск в web-источниках, чтение конкретной страницы или извлечение таблиц.

На текущем этапе browser tools работают только в read-only режиме. Им запрещено
заполнять формы, отправлять формы, нажимать кнопки подтверждения и скачивать
опасные файлы без отдельного подтверждения.

## 1C Tools

1C tools нужны для поиска документов, задач и поручений в 1С, а также чтения
карточек найденных объектов. Все 1C tools имеют `side_effect_level=read`.

На текущем этапе 1С работает только read-only: агент не записывает данные в 1С,
не меняет документы, не запускает согласования и не изменяет задачи.

## LLM Analytics Tools

LLM analytics tools нужны после сбора данных из Outlook, 1С, browser,
документов, файлов или базы знаний. Они не собирают данные сами; они получают
`collected_data` от Runtime и формируют структурированные выводы:

- `llm.analyze_collected_data` анализирует собранные данные;
- `llm.compare_sources` сравнивает несколько источников;
- `llm.extract_structured_facts` извлекает факты, даты, документы, статусы,
  ответственных и сроки.

## Почему LLM не вызывает инструменты напрямую

LLM Planner только выбирает инструменты из `ToolsCatalog` и предлагает план.
Он не открывает браузер, не вызывает COM, не открывает 1С и не исполняет
Python-код. Исполнение всегда идёт через цепочку:

```text
AgentSpec -> Runtime -> ToolGateway -> Tool -> Worker -> ToolResult
```

Так сохраняются permissions, HumanApproval и safe mode.

## Связка Data Tools -> Analytics -> Report

Типовой поток:

```text
Outlook / 1C / Browser / Files
  -> collected_data
  -> llm.analyze_collected_data или llm.compare_sources
  -> report.build_*_report
```

Data tools читают источники. LLM analytics формирует выводы и риски. Report tools
собирают итоговый отчёт.

## Запрещено

- Запись в 1С.
- Отправка web-форм.
- Нажатие кнопок подтверждения на сайтах.
- Изменение документов.
- Отправка писем без отдельного HumanApproval и safe mode.

