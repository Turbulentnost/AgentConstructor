"""Точка входа запуска LLM-прокси: ``python -m llm_proxy_service``."""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from llm_proxy_service.config import load_proxy_config


def _load_dotenv() -> None:
    """Подхватить переменные из .env рядом с сервисом, не переопределяя окружение."""
    for candidate in (Path(__file__).resolve().parent / ".env", Path.cwd() / ".env"):
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            os.environ.setdefault(key.strip(), value.strip())
        return


def main() -> None:
    """Запустить uvicorn с конфигурацией из окружения."""
    _load_dotenv()
    config = load_proxy_config()
    uvicorn.run(
        "llm_proxy_service.app:app",
        host=config.host,
        port=config.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
