"""Промпты LLM-управляемого цикла агента (ReAct-style, без хардкода)."""

from __future__ import annotations

import json

from agent_desktop_constructor.app.context.manager import AgentContextManager
from agent_desktop_constructor.app.llm.goal_checklist import TOOL_OUTPUT_HISTORY_LIMIT
from agent_desktop_constructor.app.llm.models import LLMImageContent, LLMMessage
from agent_desktop_constructor.app.llm.run_memory import (
    DEFAULT_RECENT_STEPS,
    PROMPT_PAYLOAD_CHARS_KEY,
    PROMPT_PAYLOAD_LIMIT_KEY,
    PROMPT_SOFT_LIMIT_CHARS,
    build_executed_steps_for_prompt,
    ensure_run_memory,
    resolve_recent_limit,
    shrink_payload_if_needed,
)
from agent_desktop_constructor.app.llm.temporal_context import build_temporal_context
from agent_desktop_constructor.app.runtime.screenshot_compress import (
    prepare_screenshot_for_llm,
)
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
  "criteria_evidence": [
    {"criterion": "текст критерия из goal_checklist", "evidence": "чем подтверждается (данные tools)"}
  ],
  "checklist_updates": [
    {"item_id": "criterion_1", "status": "done|pending|blocked", "note": "кратко"}
  ],
  "human_question": null,
  "human_options": [],
  "confidence": 0.0,
  "warnings": [],
  "memory_notes": ["короткий факт для памяти (опционально), без дампов stdout"]
}

ОБЯЗАТЕЛЬНЫЙ этап THINK:
- Поле thought ОБЯЗАТЕЛЬНО и должно идти ПЕРЕД действием. Нельзя сразу вызвать
  инструмент или завершить задачу, не заполнив thought.understanding.
- Для call_tool дополнительно обязательны thought.why и хотя бы один
  thought.planned_actions.
- Сверяйся с goal_checklist: что ещё pending, что уже можно закрыть.
- Сначала обдумай (THINK): что понял, чего не хватает, что планируешь, какой
  инструмент нужен и почему. Затем выбери действие (ACT). Runtime исполнит его и
  вернёт результат (OBSERVE), после чего ты снова обдумываешь (THINK) следующий шаг.

ВАЖНО про decision_type:
- decision_type принимает ТОЛЬКО: call_tool, finish_success, finish_failed,
  ask_human, request_credentials (допустимы синонимы retry_tool /
  call_additional_tool как вызов инструмента).
- НЕ используй replan_graph — в этом режиме он не поддержан.
- НИКОГДА не пиши имя инструмента (например "browser.screenshot") в decision_type.
- Чтобы вызвать инструмент: decision_type="call_tool", а имя инструмента —
  строго внутри tool_call.tool_name, параметры — внутри tool_call.input_data.
- finish_success разрешён только с criteria_evidence по обязательным критериям
  goal_checklist (или после checklist_updates status=done). Без доказательств
  Runtime отклонит завершение и попросит продолжить.
- memory_notes (опционально): 0–3 коротких факта для rolling memory
  (пути к файлам, роли листов, выводы). Без сырого stdout/таблиц.
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
и исполняется внутри папки code рабочей директории агента. Для code.run_python
в sandbox есть бюджет автозапусков (несколько подряд без паузы человеку) — чтобы
ты мог чинить stderr через rewrite→rerun; когда бюджет исчерпан, Runtime спросит
подтверждение.

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
- Если собранных данных достаточно для цели — верни finish_success с
  final_message и criteria_evidence по пунктам goal_checklist (criterion +
  evidence из collected_data / observation_history). НЕ используй шаблонные
  или выдуманные факты — только реальные собранные данные.
- Поле confidence: ставь честную оценку 0..1. Если уверенность ниже порога
  агента (low_confidence_threshold), Runtime отклонит finish_success — тогда
  собери ещё данные или спроси человека (ask_human).
- Смотри observation_history / executed_steps: это ОКНЕЕ окно шагов, не вся
  история. Ранние шаги сжаты в run_memory (facts/artifacts/last_failures).
  В executed_steps при ошибке читай error_message целиком.
- Полные выводы инструментов лежат в workspace и transcript на диске. При сомнении
  ПЕРЕЧИТАЙ файл инструментом (excel.*, code.run_python, attachment.* и т.п.) —
  не проси Runtime вернуть весь stdout в JSON и не копируй дампы в свой ответ.
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
- НИКОГДА не копируй сырой stdout/stderr, JSON-дампы или большие таблицы в поля
  thought / reason / final_message / criteria_evidence / tool_call.input_data.
  В промпте для объёмных выводов остаются только summary и пути к файлам —
  опирайся на них. В final_message дай краткий итог и ссылки на сохранённые файлы;
  иначе JSON-ответ обрежется по лимиту токенов и станет невалидным.

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

Браузер и авторизованная сессия (ОБЯЗАТЕЛЬНО):
- По умолчанию ВСЕГДА работай в уже существующей пользовательской сессии браузера
  (cookies/логины пользователя), а НЕ создавай новый пустой automation-профиль.
- При открытии сайта: browser.open_browser ИЛИ browser.navigate с
  use_default_profile=true (и нужным browser_id, если браузер назван).
- НЕ передавай use_default_profile=false и НЕ уходи в automation, если нужна
  текущая авторизация пользователя. Automation — только если человек явно просит
  чистый/изолированный профиль без логинов.
- Если browser уже открыт (есть browser.open_browser / browser.navigate в
  collected_data/tool_outputs) — НЕ открывай новый браузер и НЕ меняй профиль:
  наследуй browser_id/url/use_default_profile; для screenshot/click/type_text/
  scroll/extract_table достаточно продолжить в той же сессии.
- Не передавай profile_name="Default" сам: активная сессия может быть в другом
  профиле. profile_name — только если человек явно назвал профиль.

Взаимодействие с UI сайтов (vision-режим):
- Если для задачи нужно не просто прочитать текст страницы, а взаимодействовать с
  интерфейсом (нажать кнопку, ввести текст, перейти по элементу, открыть раздел),
  используй vision-инструменты браузера: browser.navigate (открыть URL в
  пользовательской сессии), browser.screenshot (обновить кадр),
  browser.get_page_html (HTML/DOM текущей вкладки), browser.click (клик по x,y),
  browser.type_text (ввод текста в активное поле), browser.press_key
  (enter/tab/escape/стрелки), browser.scroll (прокрутка).
- К твоему сообщению прикладывается АКТУАЛЬНЫЙ СКРИНШОТ, если он есть.
  В OS fallback это либо окно браузера (capture_mode=browser_window), либо
  virtual desktop. Координаты browser.click/scroll ОБЯЗАТЕЛЬНО в пикселях
  приложенной картинки: 0 ≤ x < image_width, 0 ≤ y < image_height из
  screen_context (это размеры именно image, не desktop_*). Runtime сам
  переведёт их в экранные координаты. Не используй desktop_width/height для клика.
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
    prior_chars = runtime_state.variables.get(PROMPT_PAYLOAD_CHARS_KEY)
    recent_limit = resolve_recent_limit(
        prior_chars if isinstance(prior_chars, int) else None
    )
    observation_history = _sanitize_observation_history(
        runtime_state.variables.get("tool_output_history", []),
        recent_limit=recent_limit,
    )
    goal_checklist = runtime_state.variables.get("goal_checklist") or []
    run_memory = ensure_run_memory(runtime_state.variables)
    last_screenshot_raw = runtime_state.variables.get("last_screenshot")
    last_screenshot = prepare_screenshot_for_llm(
        last_screenshot_raw if isinstance(last_screenshot_raw, dict) else None
    )
    executed_steps = build_executed_steps_for_prompt(
        runtime_state.tool_results,
        recent_limit=recent_limit,
    )
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
        "goal_checklist": goal_checklist,
        "run_memory": {
            "facts": run_memory.get("facts", []),
            "artifacts": run_memory.get("artifacts", []),
            "last_failures": run_memory.get("last_failures", []),
            "open_questions": run_memory.get("open_questions", []),
            "compacted_steps": run_memory.get("compacted_steps", 0),
            "note": (
                "Сжатая память ранних шагов. Полные выводы — в workspace/transcript; "
                "при необходимости читай файлы инструментами, не проси весь stdout."
            ),
        },
        "available_tools": tools_context,
        "executed_steps": executed_steps,
        "executed_steps_note": (
            f"Показаны только последние {recent_limit} шагов "
            f"(всего выполнено {len(runtime_state.tool_results)}). "
            "Раньше — в run_memory и на диске."
        ),
        "executed_actions": executed_signatures,
        "your_recent_steps": _recent_reasoning(runtime_state),
        "collected_data": collected_data,
        "observation_history": observation_history,
        "repeat_notes": repeat_notes,
        "human_responses": runtime_state.variables.get("human_responses", []),
        "decision_schema": AGENT_LOOP_SCHEMA_DESCRIPTION,
    }
    attached_files = runtime_state.variables.get("attached_files")
    workspace_files = runtime_state.variables.get("workspace_files")
    if workspace_files:
        user_payload["workspace_files"] = workspace_files
    if attached_files:
        user_payload["attached_files"] = attached_files
        user_payload["attached_files_note"] = (
            "Пользователь прикрепил файлы. Краткое содержимое — в attached_files; "
            "сами файлы лежат в рабочей папке агента (см. также workspace_files). "
            "Если workspace_files уже непустой — не утверждай, что папка пуста: "
            "сразу читай нужные файлы через excel.read_workbook(filename=имя). "
            "excel.list_files можно вызывать повторно после ответа человека. "
            "Для текста/CSV содержимое уже в attached_files.content; при правках "
            "используй excel.* или code.write_python/code.run_python."
        )
    elif workspace_files:
        user_payload["attached_files_note"] = (
            "В рабочей папке агента уже есть файлы (workspace_files). "
            "Читай их через excel.read_workbook(filename=имя из списка). "
            "Не завершай задачу с ошибкой «файлов нет», пока workspace_files непустой."
        )
    if isinstance(last_screenshot, dict) and last_screenshot.get("base64"):
        capture_mode = last_screenshot.get("capture_mode")
        monitor_count = last_screenshot.get("monitor_count")
        image_w = last_screenshot.get("image_width") or last_screenshot.get(
            "viewport_width"
        )
        image_h = last_screenshot.get("image_height") or last_screenshot.get(
            "viewport_height"
        )
        if capture_mode == "browser_window":
            note = (
                "Приложен скриншот ОКНА БРАУЗЕРА. Координаты browser.click — "
                f"в пикселях этой картинки (0..{image_w - 1 if image_w else '?'}, "
                f"0..{image_h - 1 if image_h else '?'}). Не используй desktop_*."
            )
        elif capture_mode == "virtual_desktop" or (
            isinstance(monitor_count, int) and monitor_count > 1
        ):
            note = (
                "Приложен скриншот virtual desktop "
                f"(мониторов: {monitor_count or '?'}). Координаты browser.click — "
                f"ТОЛЬКО в пикселях приложенной картинки "
                f"({image_w}×{image_h}), не desktop_width/height. "
                "Runtime масштабирует клик сам."
            )
        else:
            note = (
                "Приложен скриншот. Координаты browser.click — в пикселях этой "
                f"картинки ({image_w}×{image_h})."
            )
        user_payload["screen_context"] = {
            "has_screenshot": True,
            "url": last_screenshot.get("url"),
            "title": last_screenshot.get("title"),
            "viewport_width": image_w,
            "viewport_height": image_h,
            "image_width": image_w,
            "image_height": image_h,
            "desktop_width": last_screenshot.get("desktop_width"),
            "desktop_height": last_screenshot.get("desktop_height"),
            "capture_mode": capture_mode,
            "monitor_count": monitor_count,
            "screen_origin_x": last_screenshot.get("screen_origin_x"),
            "screen_origin_y": last_screenshot.get("screen_origin_y"),
            "coord_space": "image",
            "note": note,
        }
    elif isinstance(last_screenshot_raw, dict) and (
        last_screenshot_raw.get("base64")
        or last_screenshot_raw.get("attach_to_llm") is False
    ):
        user_payload["screen_context"] = {
            "has_screenshot": False,
            "url": last_screenshot_raw.get("url"),
            "title": last_screenshot_raw.get("title"),
            "viewport_width": last_screenshot_raw.get("viewport_width"),
            "viewport_height": last_screenshot_raw.get("viewport_height"),
            "note": (
                "Скриншот был захвачен, но не приложен к LLM (слишком большой даже "
                "после сжатия или отключён после timeout). Ориентируйся на "
                "url/title и observation_history; при необходимости вызови "
                "browser.screenshot снова или работай через DOM/CDP, если доступен."
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
    shrink_payload_if_needed(user_payload, soft_limit=PROMPT_SOFT_LIMIT_CHARS)
    budget = user_payload.get("_prompt_budget")
    if isinstance(budget, dict):
        runtime_state.variables[PROMPT_PAYLOAD_CHARS_KEY] = int(
            budget.get("chars") or 0
        )
        runtime_state.variables[PROMPT_PAYLOAD_LIMIT_KEY] = int(
            budget.get("limit") or PROMPT_SOFT_LIMIT_CHARS
        )

    user_prompt = (
        "Определи следующий безопасный шаг агента и верни JSON-решение. "
        "Инструменты выбирай сам, опираясь на их описание (description) и "
        "when_to_use в available_tools, на цель пользователя и на уже собранные "
        "данные (collected_data / run_memory). Не полагайся на подсказки по "
        "конкретным задачам — их нет; сам реши, какой инструмент и с какими "
        "параметрами нужен сейчас. Полные выводы ранних шагов на диске "
        "(workspace/transcript) — при сомнении читай файл инструментом, "
        "не проси вернуть весь stdout в JSON. "
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
                "required_inputs": _schema_required_fields(item.input_schema),
                "input_properties": _schema_property_names(item.input_schema),
                "side_effect_level": item.side_effect_level.value,
                "requires_human_approval": item.requires_human_approval,
                "output_keys": sorted(
                    item.output_schema.get("properties", {}).keys()
                ),
            }
        )
    return context


def _schema_required_fields(schema: dict | None) -> list[str]:
    """Вернуть required-поля JSON Schema без полного дерева schema."""
    if not isinstance(schema, dict):
        return []
    required = schema.get("required")
    if isinstance(required, list):
        return [str(item) for item in required if str(item).strip()]
    return []


def _schema_property_names(schema: dict | None, limit: int = 12) -> list[str]:
    """Имена свойств input_schema — компактнее полной схемы."""
    if not isinstance(schema, dict):
        return []
    props = schema.get("properties")
    if not isinstance(props, dict):
        return []
    return sorted(str(key) for key in props.keys())[:limit]


def _recent_reasoning(runtime_state: AgentRuntimeState, limit: int = 8) -> list[dict]:
    """Собрать краткую историю собственных решений LLM — её «память диалога»."""
    decisions = runtime_state.variables.get("loop_decisions", [])
    if not isinstance(decisions, list):
        return []
    # Хронологически сопоставляем call_tool → следующий результат того же tool.
    remaining_results = list(runtime_state.tool_results)
    paired: list[dict] = []
    for item in decisions:
        if not isinstance(item, dict):
            continue
        tool_call = item.get("tool_call") or {}
        tool_name = tool_call.get("tool_name")
        outcome = None
        if tool_name:
            for index, record in enumerate(remaining_results):
                if record.tool_name != tool_name:
                    continue
                outcome = {
                    "ok": record.ok,
                    "error_message": (record.error_message or "")[:300]
                    if not record.ok
                    else None,
                    "summary": _summarize_output(record.output_data, max_chars=200),
                }
                del remaining_results[index]
                break
        thought = item.get("thought") or {}
        paired.append(
            {
                "decision": item.get("decision_type"),
                "tool": tool_name,
                "input": tool_call.get("input_data"),
                "reason": str(item.get("reason") or "")[:300],
                "understanding": str(thought.get("understanding") or "")[:200],
                "confidence": item.get("confidence"),
                "outcome": outcome,
            }
        )
    return paired[-limit:]


def _sanitize_observation_history(
    history: object,
    *,
    recent_limit: int = DEFAULT_RECENT_STEPS,
) -> list[dict]:
    """Сжать историю наблюдений для промпта (без тяжёлых html/base64)."""
    if not isinstance(history, list):
        return []
    window = min(max(1, recent_limit), TOOL_OUTPUT_HISTORY_LIMIT)
    sanitized: list[dict] = []
    for item in history[-window:]:
        if not isinstance(item, dict):
            continue
        output = item.get("output")
        if isinstance(output, dict):
            output = _sanitize_collected_data({"_": output}).get("_")
        sanitized.append(
            {
                "step": item.get("step"),
                "tool_name": item.get("tool_name"),
                "ok": item.get("ok"),
                "error_message": item.get("error_message"),
                "output_summary": _summarize_output(
                    output if isinstance(output, dict) else {"value": output},
                    max_chars=500,
                ),
            }
        )
    return sanitized


# Поля с полным текстом вывода → предпочитаемый ключ summary (если уже есть).
_FULL_TEXT_TO_SUMMARY = (
    ("stdout", "stdout_summary"),
    ("stderr", "stderr_summary"),
)
# Любая строка/сериализованное значение длиннее порога сжимается в промпте.
_MAX_COLLECTED_FIELD_CHARS = 2_500


def _sanitize_collected_data(collected_data: dict) -> dict:
    """Убрать тяжёлые base64/HTML/stdout из данных, отправляемых текстом в промпт.

    Полные дампы (stdout скрипта, HTML страницы) раздувают контекст и провоцируют
    модель вставлять их обратно в JSON решения — ответ обрезается по max_tokens
    («Unterminated string»). В промпте оставляем summary + длины/флаги.
    """
    if not isinstance(collected_data, dict):
        return collected_data
    sanitized: dict = {}
    for tool_name, output in collected_data.items():
        if not isinstance(output, dict):
            sanitized[tool_name] = _trim_prompt_value(output)
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
        for full_key, summary_key in _FULL_TEXT_TO_SUMMARY:
            value = trimmed.get(full_key)
            if not isinstance(value, str):
                continue
            trimmed.pop(full_key, None)
            if summary_key not in trimmed or not str(trimmed.get(summary_key) or "").strip():
                trimmed[summary_key] = value[:2000] + ("…" if len(value) > 2000 else "")
            trimmed[f"{full_key}_length"] = len(value)
            trimmed[f"{full_key}_omitted"] = True
            if len(value) > 2000:
                trimmed[f"{full_key}_truncated"] = True
        sanitized[tool_name] = {
            key: _trim_prompt_value(value) for key, value in trimmed.items()
        }
    return sanitized


def _trim_prompt_value(value: object) -> object:
    """Сжать слишком длинные строки/структуры в collected_data для промпта."""
    if isinstance(value, str):
        if len(value) <= _MAX_COLLECTED_FIELD_CHARS:
            return value
        return (
            value[:_MAX_COLLECTED_FIELD_CHARS]
            + f"… [truncated {len(value) - _MAX_COLLECTED_FIELD_CHARS} chars]"
        )
    if isinstance(value, (dict, list)):
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(value)
        if len(text) <= _MAX_COLLECTED_FIELD_CHARS:
            return value
        return {
            "_summary": text[:_MAX_COLLECTED_FIELD_CHARS] + "…",
            "_truncated": True,
            "_original_chars": len(text),
        }
    return value


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
