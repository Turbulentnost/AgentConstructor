"""Живая проверка: LLM понимает запрос, строит план из ToolsCatalog и выполняет его.

Скрипт по очереди пробует провайдеров из .env:
  1. Claude (Anthropic, OPENAI_API_KEY_CLAUDE)
  2. OpenAI (OPENAI_API_KEY)
  3. LM Studio (локальный OpenAI-compatible endpoint) — как запасной вариант.

Первый рабочий провайдер используется для:
  - LLMToolPlanner: LLM сама выбирает tool_name из ToolsCatalog и строит шаги;
  - AgentBuilder(use_llm_planner=True): собирает AgentSpec из LLM-плана;
  - SimpleAgentRuntime + ToolGateway: безопасно исполняет план, вызывая инструменты;
  - llm.analyze_collected_data: делает аналитический вывод тем же провайдером.

LLM НЕ вызывает инструменты напрямую и не работает с COM/1С/браузером —
Runtime исполняет план через ToolGateway, а dangerous/write требуют HumanApproval.
"""

from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent_desktop_constructor.app.core.models.agent_validation import (
    AgentValidationStatus,
)
from agent_desktop_constructor.app.core.services.agent_validation_service import (
    AgentValidationService,
)
from agent_desktop_constructor.app.llm.client_factory import build_llm_client
from agent_desktop_constructor.app.llm.errors import LLMError
from agent_desktop_constructor.app.llm.models import LLMMessage, LLMRequest
from agent_desktop_constructor.app.llm.tool_planner import LLMToolPlanner
from agent_desktop_constructor.app.tools.llm_analysis_tools import (
    register_llm_analysis_tools,
)
from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.core.models.llm_config import LLMConfig
from agent_desktop_constructor.core.models.tooling import (
    ToolCallResult,
    ToolDefinition,
    ToolExecutionMode,
)
from agent_desktop_constructor.tools.base import BaseTool
from agent_desktop_constructor.tools.catalog import ToolsCatalog
from agent_desktop_constructor.tools.catalog_loader import load_tools_catalog
from agent_desktop_constructor.tools.fake_task_control_tools import (
    FakeEmailCreateDraftTool,
    FakeEmailSendTool,
    FakeLLMExtractStructuredFactsTool,
    FakeOneCGetTaskCardTool,
    FakeOneCSearchTasksTool,
    FakeOutlookReadCalendarTool,
    FakeOutlookReadTasksTool,
    FakeOutlookSearchMailTool,
    FakeReportBuildTaskReportTool,
)
from agent_desktop_constructor.tools.gateway import ToolGateway
from agent_desktop_constructor.tools.registry import ToolRegistry
from agent_desktop_constructor.tools.report_tools import register_report_tools
from agent_desktop_constructor.runtime.simple_runtime import SimpleAgentRuntime


USER_REQUESTS = [
    "Нужен агент, который смотрит все совещания в Outlook и выводит как лучше "
    "распланировать свой график",
    "Собери мои поручения из почты Outlook и из 1С и подготовь отчёт с рисками просрочки",
]


def load_env(path: Path) -> dict[str, str]:
    """Прочитать .env как простой key=value без внешних зависимостей."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def build_provider_candidates(env: dict[str, str]) -> list[LLMConfig]:
    """Собрать список провайдеров в порядке приоритета: Claude, OpenAI, LM Studio."""
    candidates: list[LLMConfig] = []
    claude_key = env.get("OPENAI_API_KEY_CLAUDE")
    if claude_key:
        candidates.append(
            LLMConfig(
                provider="anthropic",
                base_url="https://api.anthropic.com",
                model_name="claude-sonnet-4-6",
                api_key=claude_key,
                timeout_seconds=90,
            )
        )
    openai_key = env.get("OPENAI_API_KEY")
    if openai_key:
        candidates.append(
            LLMConfig(
                provider="openai_compatible",
                base_url="https://api.openai.com",
                model_name="gpt-4o-mini",
                api_key=openai_key,
                timeout_seconds=60,
            )
        )
    candidates.append(
        LLMConfig(
            provider="openai_compatible",
            base_url="http://192.168.1.157:1234",
            model_name="openai/gpt-oss-120b",
            timeout_seconds=60,
        )
    )
    return candidates


def provider_label(config: LLMConfig) -> str:
    """Человекочитаемое имя провайдера."""
    return f"{config.provider} · {config.model_name} · {config.base_url}"


def ping_provider(config: LLMConfig) -> tuple[bool, str]:
    """Проверить доступность провайдера коротким запросом."""
    client = build_llm_client(config)
    try:
        response = client.complete(
            LLMRequest(
                messages=[
                    LLMMessage(
                        role="user",
                        content="Ответь одним словом: готов",
                    )
                ],
                temperature=0.0,
                model_name=config.model_name,
            )
        )
    except LLMError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001 — диагностический скрипт
        return False, f"{type(exc).__name__}: {exc}"
    return True, response.content.strip()[:80]


class StubTool(BaseTool):
    """Заглушка каталожного инструмента для безопасного пробного запуска."""

    def __init__(self, definition: ToolDefinition, output_schema_keys: list[str]) -> None:
        super().__init__(definition)
        self._keys = output_schema_keys

    def execute(self, input_data: dict) -> ToolCallResult:
        """Вернуть непустой структурированный результат по ключам схемы."""
        output: dict = {key: [{"note": "stub"}] for key in self._keys}
        if not output:
            output = {"result": "stub"}
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data=output,
        )


def build_run_registry(catalog: ToolsCatalog, client) -> ToolRegistry:
    """Собрать реестр: реальные fake-данные + LLM-анализ + заглушки на остальное."""
    registry = ToolRegistry()
    for tool in [
        FakeOutlookSearchMailTool(),
        FakeOutlookReadCalendarTool(),
        FakeOutlookReadTasksTool(),
        FakeOneCSearchTasksTool(),
        FakeOneCGetTaskCardTool(),
        FakeLLMExtractStructuredFactsTool(),
        FakeReportBuildTaskReportTool(),
        FakeEmailCreateDraftTool(),
        FakeEmailSendTool(),
    ]:
        registry.register(tool)
    register_report_tools(registry, skip_existing=True)
    register_llm_analysis_tools(registry, client, skip_existing=True)

    for item in catalog.tools:
        if registry.has_tool(item.name):
            continue
        definition = ToolDefinition(
            name=item.name,
            title=item.title,
            description=item.description,
            side_effect_level=item.side_effect_level,
            execution_mode=ToolExecutionMode.LOCAL,
            requires_human_approval=item.requires_human_approval,
            input_schema={"type": "object"},
            output_schema=item.output_schema,
        )
        keys = list(item.output_schema.get("properties", {}).keys())
        registry.register(StubTool(definition, keys))
    return registry


def print_plan(plan) -> None:
    """Показать план, построенный LLM."""
    print(f"  Агент: {plan.agent_name}")
    print(f"  Цель: {plan.goal}")
    print("  Инструменты, выбранные LLM:")
    for tool in plan.selected_tools:
        required = "обязательный" if tool.required else "опциональный"
        print(f"    - {tool.tool_name} ({required}): {tool.reason}")
    print("  Шаги плана (цепочка):")
    for step in plan.steps:
        arrow = f" -> {step.tool_name}" if step.tool_name else ""
        print(f"    {step.step_id} [{step.step_type}]{arrow}: {step.title}")
    if plan.missing_data:
        print(f"  Не хватает данных: {plan.missing_data}")
    if plan.warnings:
        print(f"  Предупреждения: {plan.warnings}")


def run_request(
    request: str,
    planner: LLMToolPlanner,
    catalog: ToolsCatalog,
    client,
) -> None:
    """Спланировать, собрать и выполнить агента для одного запроса."""
    print("\n" + "=" * 78)
    print(f"ЗАПРОС: {request}")
    print("=" * 78)

    print("\n[1] LLM строит план из ToolsCatalog...")
    plan = planner.plan(request, catalog)
    print_plan(plan)

    print("\n[2] AgentBuilder собирает AgentSpec из LLM-плана...")
    builder = AgentBuilder(
        tools_catalog=catalog,
        llm_planner=planner,
        use_llm_planner=True,
    )
    agent_spec = builder.build_from_request(request)
    tool_nodes = [n.tool_name for n in agent_spec.graph_nodes if n.tool_name]
    print(f"  Граф tool-узлов: {tool_nodes}")

    print("\n[3] Runtime выполняет план через ToolGateway...")
    registry = build_run_registry(catalog, client)
    runtime = SimpleAgentRuntime(ToolGateway(registry))
    service = AgentValidationService(
        agent_service=None,
        runtime=runtime,
        tool_registry=registry,
        tools_catalog=catalog,
    )
    result = service.validate_agent(agent_spec, request)

    print(f"  Статус: {result.status.value}")
    if result.critical_errors:
        print(f"  Критические ошибки: {result.critical_errors}")
    if result.errors and result.status != AgentValidationStatus.PASSED:
        print(f"  Ошибки: {result.errors}")
    if result.final_message:
        print("\n  ИТОГОВЫЙ ВЫВОД АГЕНТА:")
        for line in str(result.final_message).splitlines():
            print(f"    {line}")


def main() -> int:
    """Точка входа живой проверки."""
    env = load_env(PROJECT_ROOT / ".env")
    catalog = load_tools_catalog()
    candidates = build_provider_candidates(env)

    print("Проверка доступности провайдеров (приоритет: Claude -> OpenAI -> LM Studio):")
    working_config: LLMConfig | None = None
    for config in candidates:
        print(f"\n- Пробую: {provider_label(config)}")
        ok, detail = ping_provider(config)
        if ok:
            print(f"  OK: {detail}")
            working_config = config
            break
        print(f"  Недоступен: {detail}")

    if working_config is None:
        print("\nНи один провайдер недоступен. Проверьте ключи в .env и сеть.")
        return 1

    print(f"\nИспользую провайдера: {provider_label(working_config)}")
    client = build_llm_client(working_config)
    planner = LLMToolPlanner(client)

    for request in USER_REQUESTS:
        try:
            run_request(request, planner, catalog, client)
        except Exception as exc:  # noqa: BLE001 — диагностический скрипт
            print(f"\n  Ошибка при обработке запроса: {type(exc).__name__}: {exc}")

    print("\nГотово.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
