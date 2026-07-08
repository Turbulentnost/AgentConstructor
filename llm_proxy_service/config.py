"""Конфигурация цепочки upstream-LLM для прокси.

Порядок backend-ов задаётся переменной ``LLM_PROXY_CHAIN`` (по умолчанию
``chatgpt,lmstudio``). Каждый backend настраивается своими переменными
окружения с префиксом по имени, что позволяет менять модели/ключи без правки кода.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace

DEFAULT_CHAIN = "chatgpt,lmstudio"

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
    "lmstudio": {
        "style": STYLE_OPENAI,
        "base_url": "http://192.168.1.157:1234",
        "model": "openai/gpt-oss-120b",
        "api_key_env": "",
        "display_name": "LM Studio (gpt-oss-120b)",
    },
}

REASONING_MODES = ("internal", "reason")


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
    reasoning_mode: str | None = None

    def model_ids(self) -> list[str]:
        """Вернуть selectable id модели для OpenAI-compatible /v1/models."""
        ids = [self.name]
        if self.supports_reasoning:
            ids.extend(f"{self.name}:{mode}" for mode in REASONING_MODES)
        return ids

    def with_reasoning(self, mode: str | None) -> BackendConfig:
        """Вернуть backend с выбранным режимом reasoning."""
        if mode is None:
            return self
        normalized = mode.strip().casefold()
        if normalized not in REASONING_MODES or not self.supports_reasoning:
            return self
        return replace(self, reasoning_mode=normalized)


@dataclass(frozen=True)
class ProxyConfig:
    """Итоговая конфигурация прокси-сервиса."""

    host: str
    port: int
    chain: list[BackendConfig] = field(default_factory=list)


def _env(name: str, default: str = "") -> str:
    """Прочитать переменную окружения с обрезкой пробелов."""
    return (os.environ.get(name) or default).strip()


def _env_bool(name: str, default: str = "") -> bool:
    """Прочитать boolean из окружения."""
    value = _env(name, default).casefold()
    return value in {"1", "true", "yes", "on", "да"}


def _backend_from_env(name: str, default_timeout: float) -> BackendConfig:
    """Собрать BackendConfig из env, опираясь на встроенные дефолты по имени."""
    key = name.strip().casefold()
    defaults = _BUILTIN_DEFAULTS.get(key, {})
    prefix = f"LLM_PROXY_{key.upper()}_"

    style = _env(f"{prefix}STYLE", defaults.get("style", STYLE_OPENAI)) or STYLE_OPENAI
    base_url = _env(f"{prefix}BASE_URL", defaults.get("base_url", ""))
    model = _env(f"{prefix}MODEL", defaults.get("model", ""))
    display_name = _env(f"{prefix}DISPLAY_NAME", defaults.get("display_name", key))
    supports_reasoning = _env_bool(
        f"{prefix}SUPPORTS_REASONING",
        defaults.get("supports_reasoning", "false"),
    )

    # API-ключ: сначала прямой LLM_PROXY_<NAME>_API_KEY, иначе из указанной env.
    api_key = _env(f"{prefix}API_KEY")
    if not api_key:
        api_key_env = _env(f"{prefix}API_KEY_ENV", defaults.get("api_key_env", ""))
        if api_key_env:
            api_key = _env(api_key_env)

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
    )


def load_proxy_config() -> ProxyConfig:
    """Загрузить ProxyConfig из окружения."""
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
