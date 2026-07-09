"""Промпты LLM-управляемого цикла агента (ReAct-style, без хардкода)."""

from __future__ import annotations

import json

from agent_desktop_constructor.app.context.manager import AgentContextManager
from agent_desktop_constructor.app.llm.models import LLMImageContent, LLMMessage
from agent_desktop_constructor.app.llm.temporal_context import build_temporal_context
from agent_desktop_constructor.core.models.agent_spec import AgentSpec
from agent_desktop_constructor.core.models.runtime_state import AgentRuntimeState
from agent_desktop_constructor.tools.catalog import ToolsCatalog

AGENT_LOOP_SCHEMA_DESCRIPTION = """
Верни только JSON-объект без Markdown:
{
  "thought": {
    "understanding": "что ты понял из задачи и уже собранных данных (обязательно, непусто)",
    "missing_info": "чего ещё не хватает для достижения цели",
    "planned_actions": ["какие шаги планируешь дальше"],
    "chosen_tool": "какой инструмент нужен именно сейчас (или null, если завершаешь)",
    "why": "почему именно это действие сейчас"
  },
  "decision_type": "call_tool | finish_success | finish_failed | ask_human | request_credentials",
  "reason": "почему ты выбрал это действие на основе цели и уже собранных данных",
  "tool_call": {
    "tool_name": "точное имя инструмента из списка доступных",
    "input_data": {"параметр": "значение"},
    "reason": "зачем нужен именно этот инструмент сейчас"
  },
  "final_message": "итоговый вывод для пользователя на основе собранных данных (для finish_success)",
  "human_question": null,
  "human_options": [],
  "confidence": 0.0,
  "warnings": []
}

ОБЯЗАТЕЛЬНЫЙ этап THINK:
- Поле thought ОБЯЗАТЕЛЬНО и должно идти ПЕРЕД действием. Нельзя сразу вызвать
  инструмент или завершить задачу, не заполнив thought.understanding.
- Сначала обдумай (THINK): что понял, чего не хватает, что планируешь, какой
  инструмент нужен и почему. Затем выбери действие (ACT). Runtime исполнит его и
  вернёт результат (OBSERVE), после чего ты снова обдумываешь (THINK) следующий шаг.

ВАЖНО про decision_type:
- decision_type принимает ТОЛЬКО одно из значений: call_tool, finish_success,
  finish_failed, ask_human, request_credentials (а также retry_tool,
  call_additional_tool, replan_graph, continue_to_next).
- НИКОГДА не пиши имя инструмента (например "browser.screenshot") в decision_type.
- Чтобы вызвать инструмент: decision_type="call_tool", а имя инструмента —
  строго внутри tool_call.tool_name, параметры — внутри tool_call.input_data.
""".strip()


def build_agent_loop_prompt(
    agent_spec: AgentSpec,
    runtime_state: AgentRuntimeState,
    tools_catalog: ToolsCatalog,
    executed_signatures: list[str],
    repeat_notes: list[str],
) -> list[LLMMessage]:
    """Собрать prompt одного шага LLM-управляемого цикла агента."""
    system_prompt = """
Ты — управляющий LLM ИИ-агента. Ты сам планируешь, как достичь цели пользователя.
После каждого результата инструмента ты решаешь следующий шаг.

Работай строго по циклу THINK → ACT → OBSERVE:
- THINK (обязательно каждый шаг): сначала заполни поле thought — что понял, чего
  не хватает, какие действия планируешь, какой инструмент нужен и почему. Без
  этого этапа действовать нельзя.
- ACT: только после THINK выбери ОДНО действие (decision_type): вызвать инструмент,
  завершить успехом/ошибкой, спросить человека или запросить credentials. Ты не
  исполняешь инструменты сам — Runtime безопасно исполнит их через ToolGateway.
- OBSERVE: Runtime вернёт результат инструмента, и ты снова перейдёшь к THINK.

Ты не пишешь и не запускаешь код напрямую в своём ответе. Но если задача требует
обработки данных, ты можешь ВЫБРАТЬ действия code.write_python (написать программу
на Python) и code.run_python (запустить её). Runtime лишь проверит, что код лежит
и исполняется внутри папки code рабочей директории агента, и спросит подтверждение
перед запуском.

Правила:
- Выбирай tool_name только из списка доступных инструментов. Не выдумывай новые.
- НЕ повторяй уже выполненные действия с теми же параметрами (см. executed_actions).
- В your_recent_steps ты видишь СВОИ последние решения и их обоснования — это твоя
  память диалога. Прежде чем действовать, свери: не делаешь ли ты то же самое, что
  и на прошлых шагах. Если несколько раз подряд выбирал одно действие, а результат
  (collected_data/скриншот/метрики) не меняется — СМЕНИ стратегию или заверши.
- Для прокрутки смотри поля scrolled и at_bottom/at_top в результате: если
  scrolled=false или at_bottom=true — дальше в ту же сторону прокручивать бесполезно.
- Смотри на результаты уже выполненных инструментов (collected_data) и решай:
  нужно ли собрать ещё данные другим инструментом или данных уже достаточно.
- Если собранных данных достаточно для цели — верни finish_success и сформулируй
  вывод (final_message) сам, на основе запроса пользователя и собранных данных.
  НЕ используй шаблонные или выдуманные факты — только реальные собранные данные.
- Если нужный инструмент недоступен или данных получить нельзя — finish_failed или ask_human.
- write/dangerous действия исполняются только с подтверждением человека.

Обработка больших данных программой (а не вручную):
- Большие таблицы, списки и объёмные данные НЕ пересказывай и не переписывай сам —
  это делает написанная тобой программа. Правильная архитектура: выгрузи исходные
  данные в файл (например browser.dump_page_source сохраняет HTML и CSS страницы в
  page_dumps/<имя>/page.html), затем напиши парсер (code.write_python) и запусти его
  (code.run_python). cwd скрипта — рабочая папка агента, поэтому он читает выгруженный
  файл по возвращённому пути и может сохранить результат (например .xlsx/.csv).
- Если скрипт упал (см. stderr в результате code.run_python) — обдумай ошибку в THINK,
  перепиши код через code.write_python и запусти снова. Реши сам, когда данных
  достаточно и пора завершать.

Взаимодействие с человеком (ask_human / request_credentials):
- Используй ask_human в двух случаях: (1) когда нужно, чтобы человек ЧТО-ТО СДЕЛАЛ
  вручную (войти в аккаунт, ввести код из SMS/2FA, подтвердить капчу, физически
  что-то проверить), и (2) когда тебе нужен ОТВЕТ/выбор человека, чтобы продолжить.
- Всегда формулируй конкретный human_question. В human_options дай варианты ответа
  или действий (например ["Готово, я вошёл", "Не получилось"] или конкретные
  варианты выбора). Пользователю всегда доступен и свой вариант ответа.
- ПЕРЕД тем как приостановиться, в поле reason кратко опиши, ЧТО ты планируешь
  сделать дальше, ПОСЛЕ того как человек ответит/выполнит действие. Это твой план.
- После ответа человека его слова появятся в human_responses — учитывай их и
  продолжай с того места, где остановился. Работа не начинается заново, сессия
  браузера сохраняется живой, поэтому смело продолжай взаимодействие с UI.
- Для ввода логина/пароля/кода авторизации используй ask_human (пусть человек
  введёт их сам в браузере) — не пытайся ввести секреты сам.
- Outlook и 1С работают только в режиме чтения. email.send заблокирован.
- Пароли/секреты нельзя запрашивать через LLM — для авторизации верни request_credentials.

Взаимодействие с UI сайтов (vision-режим):
- Если для задачи нужно не просто прочитать текст страницы, а взаимодействовать с
  интерфейсом (нажать кнопку, ввести текст, перейти по элементу, открыть раздел),
  используй vision-инструменты браузера: browser.navigate (открыть URL),
  browser.screenshot (обновить кадр), browser.get_page_html (HTML/DOM текущей
  вкладки), browser.click (клик по x,y), browser.type_text (ввод текста в
  активное поле), browser.press_key (enter/tab/escape/стрелки), browser.scroll
  (прокрутка).
- К твоему сообщению прикладывается АКТУАЛЬНЫЙ СКРИНШОТ текущей вкладки, если он
  есть. Определяй координаты клика по скриншоту в пикселях от левого-верхнего угла;
  размеры viewport указаны в screen_context.
- browser.get_page_html — когда нужна разметка/селекторы/скрытый текст, а не
  картинка; для визуальных кликов по UI используй screenshot.
- browser.dump_page_source — когда нужно выгрузить весь HTML и CSS страницы в файлы
  для последующего разбора программой (например большую таблицу): сохрани дамп, затем
  напиши и запусти Python-парсер (code.write_python + code.run_python).
- HTML/CSS-дамп требует CDP-доступ к DOM. Если текущий браузер открыт как OS fallback
  (обычное окно без CDP), скриншот/клик работают, но DOM выгрузить нельзя. Для
  авторизованной страницы используй тот же browser_id и use_default_profile=true через
  browser.navigate; если CDP не поднялся из-за уже открытого окна, спроси человека
  закрыть это окно и повтори browser.navigate с тем же browser_id/use_default_profile.
  Не переключайся молча на другой браузер/профиль, иначе потеряешь авторизацию.
  Не передавай profile_name="Default" сам: у пользователя активная сессия может быть
  в другом профиле. profile_name указывай только если человек явно назвал профиль.
- browser.extract_table тоже является DOM/CDP-инструментом. Если страница уже открыта
  в нужном браузере, не навигируй в другой браузер и не меняй профиль: инструмент
  унаследует browser_id/url/use_default_profile из tool_outputs. Для текущей таблицы
  достаточно передать table_hint; url передавай только если нужно открыть новый URL.
- Действуй пошагово: сделай одно действие, посмотри на новый скриншот, реши следующее.
- Не вводи пароли, коды из SMS и 2FA — если сайт требует ручной вход, верни ask_human.
Ответ верни только JSON по схеме решения.
""".strip()

    allowed_tools = sorted(agent_spec.allowed_tool_names())
    tools_context = _available_tools_context(tools_catalog, allowed_tools)
    collected_data = _sanitize_collected_data(
        runtime_state.variables.get("tool_outputs", {})
    )
    last_screenshot = runtime_state.variables.get("last_screenshot")
    executed_steps = [
        {
            "tool_name": record.tool_name,
            "ok": record.ok,
            "error_type": record.error_type,
            "output_summary": _summarize_output(record.output_data),
        }
        for record in runtime_state.tool_results
    ]
    try:
        agent_context = AgentContextManager().build_llm_context(
            agent_spec=agent_spec,
            runtime_state=runtime_state,
        )
    except Exception as exc:
        agent_context = {
            "error": f"Не удалось собрать AgentContext: {exc}",
            "sections": {},
            "usage": None,
        }

    user_payload = {
        "temporal_context": build_temporal_context(),
        "agent_context": agent_context,
        "user_request": runtime_state.variables.get("user_request"),
        "goal": agent_spec.goal.model_dump(mode="json"),
        "available_tools": tools_context,
        "executed_steps": executed_steps,
        "executed_actions": executed_signatures,
        "your_recent_steps": _recent_reasoning(runtime_state),
        "collected_data": collected_data,
        "repeat_notes": repeat_notes,
        "human_responses": runtime_state.variables.get("human_responses", []),
        "decision_schema": AGENT_LOOP_SCHEMA_DESCRIPTION,
    }
    attached_files = runtime_state.variables.get("attached_files")
    if attached_files:
        user_payload["attached_files"] = attached_files
        user_payload["attached_files_note"] = (
            "Пользователь прикрепил файлы при создании агента. Их содержимое ниже, "
            "а сами файлы лежат в рабочей папке агента — их можно читать и "
            "редактировать через инструменты excel.* по имени файла."
        )
    if isinstance(last_screenshot, dict) and last_screenshot.get("base64"):
        user_payload["screen_context"] = {
            "has_screenshot": True,
            "url": last_screenshot.get("url"),
            "title": last_screenshot.get("title"),
            "viewport_width": last_screenshot.get("viewport_width"),
            "viewport_height": last_screenshot.get("viewport_height"),
            "note": (
                "К этому сообщению приложен скриншот текущей вкладки. Координаты "
                "для browser.click указывай в пикселях viewport по этому скриншоту."
            ),
        }
    last_page_html = runtime_state.variables.get("last_page_html")
    if isinstance(last_page_html, dict) and (
        last_page_html.get("html_summary") or last_page_html.get("html")
    ):
        user_payload["page_html_context"] = {
            "url": last_page_html.get("url"),
            "title": last_page_html.get("title"),
            "html_length": last_page_html.get("html_length"),
            "truncated": last_page_html.get("truncated"),
            "html_summary": last_page_html.get("html_summary")
            or str(last_page_html.get("html") or "")[:4000],
            "note": (
                "Сырой html убран из collected_data/tool_outputs, чтобы не раздувать "
                "контекст. Для DOM/селекторов используй html_summary; при необходимости "
                "вызови browser.get_page_html снова."
            ),
        }
    user_prompt = (
        "Определи следующий безопасный шаг агента и верни JSON-решение. "
        "Инструменты выбирай сам, опираясь на их описание (description) и "
        "when_to_use в available_tools, на цель пользователя и на уже собранные "
        "данные (collected_data). Не полагайся на подсказки по конкретным задачам "
        "— их нет; сам реши, какой инструмент и с какими параметрами нужен сейчас. "
        "Для относительных дат ('сегодня', 'на этой неделе', 'за июнь') используй "
        "temporal_context; если input_data инструмента содержит дату, передавай её "
        "в формате YYYY-MM-DD.\n"
        + json.dumps(user_payload, ensure_ascii=False, indent=2, default=str)
    )
    user_images: list[LLMImageContent] = []
    if isinstance(last_screenshot, dict) and last_screenshot.get("base64"):
        user_images.append(
            LLMImageContent(
                base64_data=str(last_screenshot["base64"]),
                media_type=str(last_screenshot.get("media_type") or "image/png"),
            )
        )
    return [
        LLMMessage(role="system", content=system_prompt),
        LLMMessage(role="user", content=user_prompt, images=user_images),
    ]


def _available_tools_context(
    tools_catalog: ToolsCatalog,
    allowed_tool_names: list[str],
) -> list[dict]:
    """Собрать компактное описание доступных агенту инструментов."""
    context: list[dict] = []
    for name in allowed_tool_names:
        if not tools_catalog.has_tool(name):
            continue
        item = tools_catalog.get_tool(name)
        context.append(
            {
                "tool_name": item.name,
                "description": item.description,
                "when_to_use": item.planner_hint,
                "input_schema": item.input_schema,
                "side_effect_level": item.side_effect_level.value,
                "requires_human_approval": item.requires_human_approval,
                "output_keys": sorted(
                    item.output_schema.get("properties", {}).keys()
                ),
            }
        )
    return context


def _recent_reasoning(runtime_state: AgentRuntimeState, limit: int = 8) -> list[dict]:
    """Собрать краткую историю собственных решений LLM — её «память диалога»."""
    decisions = runtime_state.variables.get("loop_decisions", [])
    if not isinstance(decisions, list):
        return []
    recent: list[dict] = []
    for item in decisions[-limit:]:
        if not isinstance(item, dict):
            continue
        tool_call = item.get("tool_call") or {}
        recent.append(
            {
                "decision": item.get("decision_type"),
                "tool": tool_call.get("tool_name"),
                "input": tool_call.get("input_data"),
                "reason": str(item.get("reason") or "")[:300],
            }
        )
    return recent


def _sanitize_collected_data(collected_data: dict) -> dict:
    """Убрать тяжёлые base64/HTML из данных, отправляемых текстом в промпт."""
    if not isinstance(collected_data, dict):
        return collected_data
    sanitized: dict = {}
    for tool_name, output in collected_data.items():
        if not isinstance(output, dict):
            sanitized[tool_name] = output
            continue
        trimmed = dict(output)
        if "screenshot_base64" in trimmed:
            trimmed.pop("screenshot_base64", None)
            trimmed["screenshot_captured"] = True
        if "html" in trimmed and isinstance(trimmed.get("html"), str):
            html = trimmed.pop("html")
            trimmed["html_captured"] = True
            if "html_length" not in trimmed:
                trimmed["html_length"] = len(html)
            if "html_summary" not in trimmed:
                trimmed["html_summary"] = html[:4000]
            if "truncated" not in trimmed:
                trimmed["truncated"] = len(html) > 4000
        sanitized[tool_name] = trimmed
    return sanitized


def _summarize_output(output_data: dict | None, max_chars: int = 600) -> str:
    """Сжать output_data инструмента до короткого текста для контекста LLM."""
    if not output_data:
        return "пустой результат"
    try:
        text = json.dumps(output_data, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(output_data)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"
