"""End-to-end прогон агента по пути desktop backend (без GUI)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent_desktop_constructor.app.core.bootstrap import build_application_container
from agent_desktop_constructor.app.core.config import (
    AppConfig,
    apply_llm_api_key_from_env,
    load_app_config_from_env,
    load_dotenv_into_environ,
)
from agent_desktop_constructor.app.core.settings import (
    DEFAULT_SETTINGS_PATH,
    load_settings,
)

REQUEST = (
    "Собери мои встречи и сообщения из почты Outlook "
    "и подготовь отчёт с рисками просрочки"
)


def main() -> int:
    load_dotenv_into_environ()
    if Path(DEFAULT_SETTINGS_PATH).exists():
        app_config = load_settings()
    else:
        app_config = load_app_config_from_env()
    app_config = apply_llm_api_key_from_env(app_config)
    print(f"run_mode={app_config.run_mode} build_mode={app_config.agent_build_mode}")
    print(f"provider={app_config.llm_provider} model={app_config.llm_model_name}")

    container = build_application_container(app_config)
    agent_spec, validation, state = (
        container.agent_service.create_validate_and_run_once(REQUEST)
    )
    print("=" * 70)
    print(f"agent: {agent_spec.name} tools={[t.tool_name for t in agent_spec.tools]}")
    print(f"STATUS: {validation.status.value}")
    print(f"summary: {validation.summary}")
    print("errors:")
    for item in validation.errors:
        print(f"  - {item}")
    if state is not None:
        chain = [
            (event.get("tool_name"), event.get("ok"))
            for event in state.variables.get("tool_call_log", [])
        ]
        print(f"run_id={state.run_id} status={state.status.value}")
        print(f"CHAIN: {chain}")
        print("repeat_notes:", state.variables.get("repeat_notes"))
    print("-" * 70)
    print("FINAL_MESSAGE:")
    print(validation.final_message or "(нет)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
