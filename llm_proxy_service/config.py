"""Конфигурация цепочки upstream-LLM для прокси.

Порядок backend-ов задаётся переменной ``LLM_PROXY_CHAIN`` (по умолчанию
``chatgpt,claude,lmstudio``). Каждый backend настраивается своими переменными
окружения с префиксом по имени, что позволяет менять модели/ключи без правки кода.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

DEFAULT_CHAIN = "chatgpt,claude,lmstudio"

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080

# Стиль общения с upstream:
#   "openai"           -> /v1/chat/completions
#   "openai_responses" -> /v1/responses (нужно для reasoning-моделей OpenAI)
#   "anthropic"        -> /v1/messages
STYLE_OPENAI = "openai"
STYLE_OPENAI_RESPONSES = "openai_responses"
STYLE_ANTHROPIC = "anthropic"

# Значения по умолчанию для каждого известного backend-а.
# ВНИМАНИЕ: model_name у ChatGPT нужно привести к реально доступным моделям
# вашего аккаунта через переменные окружения (см. .env.example).
_BUILTIN_DEFAULTS: dict[str, dict[str, str]] = {
    "chatgpt": {
        "style": STYLE_OPENAI,
        "base_url": "https://api.openai.com",
        "model": "gpt-5.5",
        "api_key_env": "OPENAI_API_KEY",
        "display_name": "Chat-GPT 5.5",
        "supports_reasoning": "true",
    },
    "claude": {
        "style": STYLE_ANTHROPIC,
        "base_url": "https://api.claudehub.fun",
        "model": "claude-sonnet-4-6",
        "models": "claude-sonnet-4-6,claude-opus-4-1",
        "api_key_env": "CLAUDE_API_KEY,OPENAI_API_KEY_CLAUDE",
        "display_name": "Claude",
        "supports_reasoning": "true",
        "discover_models": "true",
    },
    "lmstudio": {
        "style": STYLE_OPENAI,
        "base_url": "http://192.168.1.157:1234",
        "model": "openai/gpt-oss-120b",
        "api_key_env": "",
        "display_name": "LM Studio (gpt-oss-120b)",
    },
}

REASONING_MODES = ("internal", "reason")
_DOTENV_LOADED = False


@dataclass(frozen=True)
class BackendConfig:
    """Настройки одного upstream-LLM в цепочке."""

    name: str
    style: str
    base_url: str
    model: str
    api_key: str | None
    timeout_seconds: float
    display_name: str
    supports_reasoning: bool = False
    discover_models: bool = False
    configured_models: tuple[str, ...] = ()
    reasoning_mode: str | None = None
    selected_model_id: str | None = None

    def model_ids(self) -> list[str]:
        """Вернуть selectable id модели для OpenAI-compatible /v1/models."""
        ids = [self.selected_model_id or self.name]
        if self.supports_reasoning:
            ids.extend(f"{self.name}:{mode}" for mode in REASONING_MODES)
        return ids

    @property
    def upstream_model(self) -> str:
        """Вернуть конкретную upstream-модель для вызова API."""
        return self.selected_model_id or self.model

    def configured_model_ids(self) -> tuple[str, ...]:
        """Вернуть явно настроенные модели backend-а."""
        return self.configured_models or (self.model,)

    def with_reasoning(self, mode: str | None) -> BackendConfig:
        """Вернуть backend с выбранным режимом reasoning."""
        if mode is None:
            return self
        normalized = mode.strip().casefold()
        if normalized not in REASONING_MODES or not self.supports_reasoning:
            return self
        return replace(self, reasoning_mode=normalized)

    def with_model(self, model_id: str) -> BackendConfig:
        """Вернуть backend с конкретной upstream-моделью из селекта."""
        selected = model_id.strip()
        if not selected:
            return self
        return replace(self, selected_model_id=selected)


@dataclass(frozen=True)
class ProxyConfig:
    """Итоговая конфигурация прокси-сервиса."""

    host: str
    port: int
    chain: list[BackendConfig] = field(default_factory=list)


def _env(name: str, default: str = "") -> str:
    """Прочитать переменную окружения с обрезкой пробелов."""
    return (os.environ.get(name) or default).strip()


def _load_dotenv_once() -> None:
    """Подхватить .env для прокси даже при запуске через uvicorn/import.

    `python -m llm_proxy_service` уже делает это в `__main__`, но при запуске
    `uvicorn llm_proxy_service.app:app` модуль `__main__` не исполняется.
    """
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    root = Path(__file__).resolve().parents[1]
    for candidate in (Path.cwd() / ".env", root / ".env", root / "llm_proxy_service" / ".env"):
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        return


def _env_bool(name: str, default: str = "") -> bool:
    """Прочитать boolean из окружения."""
    value = _env(name, default).casefold()
    return value in {"1", "true", "yes", "on", "да"}


def _env_list(name: str, default: str = "") -> tuple[str, ...]:
    """Прочитать comma-separated список из окружения."""
    raw = _env(name, default)
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _backend_from_env(name: str, default_timeout: float) -> BackendConfig:
    """Собрать BackendConfig из env, опираясь на встроенные дефолты по имени."""
    key = name.strip().casefold()
    defaults = _BUILTIN_DEFAULTS.get(key, {})
    prefix = f"LLM_PROXY_{key.upper()}_"

    style = _env(f"{prefix}STYLE", defaults.get("style", STYLE_OPENAI)) or STYLE_OPENAI
    base_url = _env(f"{prefix}BASE_URL", defaults.get("base_url", ""))
    if key == "claude":
        base_url = _env("ANTHROPIC_BASE_URL", base_url)
    model = _env(f"{prefix}MODEL", defaults.get("model", ""))
    configured_models = _env_list(
        f"{prefix}MODELS",
        defaults.get("models", model),
    )
    display_name = _env(f"{prefix}DISPLAY_NAME", defaults.get("display_name", key))
    supports_reasoning = _env_bool(
        f"{prefix}SUPPORTS_REASONING",
        defaults.get("supports_reasoning", "false"),
    )
    discover_models = _env_bool(
        f"{prefix}DISCOVER_MODELS",
        defaults.get("discover_models", "false"),
    )

    # API-ключ: сначала прямой LLM_PROXY_<NAME>_API_KEY, иначе из указанной env.
    api_key = _env(f"{prefix}API_KEY")
    if not api_key:
        api_key_env = _env(f"{prefix}API_KEY_ENV", defaults.get("api_key_env", ""))
        if api_key_env:
            for env_name in [item.strip() for item in api_key_env.split(",") if item.strip()]:
                api_key = _env(env_name)
                if api_key:
                    break

    timeout_raw = _env(f"{prefix}TIMEOUT_SECONDS")
    timeout_seconds = float(timeout_raw) if timeout_raw else default_timeout

    return BackendConfig(
        name=key,
        style=style.casefold(),
        base_url=base_url,
        model=model,
        api_key=api_key or None,
        timeout_seconds=timeout_seconds,
        display_name=display_name,
        supports_reasoning=supports_reasoning,
        discover_models=discover_models,
        configured_models=configured_models,
    )


def load_proxy_config() -> ProxyConfig:
    """Загрузить ProxyConfig из окружения."""
    _load_dotenv_once()
    host = _env("LLM_PROXY_HOST", DEFAULT_HOST)
    port_raw = _env("LLM_PROXY_PORT")
    port = int(port_raw) if port_raw else DEFAULT_PORT

    default_timeout_raw = _env("LLM_PROXY_TIMEOUT_SECONDS")
    default_timeout = float(default_timeout_raw) if default_timeout_raw else 120.0

    chain_raw = _env("LLM_PROXY_CHAIN", DEFAULT_CHAIN)
    names = [item for item in (part.strip() for part in chain_raw.split(",")) if item]

    chain: list[BackendConfig] = []
    for name in names:
        backend = _backend_from_env(name, default_timeout)
        if not backend.base_url or not backend.model:
            # Backend без base_url/model пропускаем, чтобы не падать на старте.
            continue
        chain.append(backend)

    return ProxyConfig(host=host, port=port, chain=chain)
