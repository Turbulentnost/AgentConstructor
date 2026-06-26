# LLM Planner

Проект использует локальную OpenAI-compatible модель из `LLMConfig`:

- `base_url`: `http://192.168.1.157:1234`
- `model_name`: `openai/gpt-oss-120b`

На текущем этапе LLM-слой подготовлен только как безопасный planner. Он не
подключён к `SimpleAgentRuntime` и не выполняет инструменты.

## Граница ответственности

LLM может:

- анализировать пользовательский запрос;
- предлагать план;
- выбирать `tool_name` только из контекста `ToolsCatalog`;
- возвращать структурированный JSON;
- объяснять, каких данных не хватает;
- отмечать, что нужен человек или новый инструмент.

LLM не может:

- вызывать инструменты напрямую;
- обращаться к COM;
- отправлять письма;
- создавать черновики;
- менять календарь;
- удалять письма;
- генерировать произвольный Python-код для исполнения;
- изменять файлы.

## ToolsCatalog как единственный источник tool_name

LLM видит только текстовый контекст из `ToolsCatalog.to_planner_context()`.
Промпт запрещает придумывать новые `tool_name`. Если подходящего инструмента
нет, LLM должна вернуть:

```json
{
  "needs_human_or_new_tool": true
}
```

`AgentBuilder` обязан дополнительно проверять результат LLM по `ToolsCatalog`,
даже если LLM вернула валидный JSON.

## Структурированный JSON

Planner возвращает JSON, который валидируется через `LLMPlanningResult`:

- `understood_goal`
- `selected_tools`
- `missing_data`
- `needs_human`
- `needs_human_reason`
- `needs_human_or_new_tool`
- `warnings`

Если ответ не является JSON или не проходит Pydantic-валидацию, используется
`LLMInvalidJSONError`.

## Runtime не доверяет LLM напрямую

Даже после будущего подключения planner-а:

- `Runtime` не должен выполнять команды из свободного текста LLM;
- `Runtime` должен работать только с валидированным `AgentSpec`;
- `ToolGateway` всё равно проверяет права инструмента;
- dangerous/write действия всё равно требуют HumanApproval;
- Outlook COM остаётся только в worker-слое.

Такой порядок сохраняет инвариант: LLM планирует, но не исполняет.

## Как LLM подключается к AgentBuilder

`AgentBuilder` может использовать `LLMPlanner` только опционально:

```python
builder = AgentBuilder(
    llm_planner=llm_planner,
    use_llm_planner=True,
)
```

По умолчанию `use_llm_planner=False`, поэтому текущий эвристический Builder не
делает HTTP-запросы и не зависит от LLM.

При включении LLM порядок такой:

1. `AgentBuilder` сначала выбирает шаблон эвристическим `TemplateSelector`.
2. `LLMPlanner` получает `ToolsCatalog.to_planner_context(agent_type)`.
3. LLM возвращает только `LLMPlanningResult` в JSON.
4. `LLMPlanner` и `AgentBuilder` проверяют все `selected_tools` через
   `ToolsCatalog`.
5. Финальный `AgentSpec` всё равно строится кодом Builder-а из локальных
   шаблонов и Pydantic-моделей.
6. `validate_agent_spec_tools_against_catalog()` остаётся обязательной
   финальной проверкой.

LLM не создаёт окончательный `AgentSpec` и не управляет `Runtime`. Если модель
вернула неизвестный `tool_name`, результат отклоняется ошибкой. Если модель
считает, что подходящего инструмента нет, Builder добавляет требование к данным
`new_tool_or_human_needed`, чтобы человек принял решение.

Во время исполнения `ToolGateway` всё равно проверяет права, `allowed` и
HumanApproval. Поэтому даже ошибочный или слишком смелый план LLM не даёт
модели возможности выполнить инструмент напрямую.

