"""Конфигурация приложения и загрузка из окружения."""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from agent_desktop_constructor.app.core.app_mode import AppRunMode
from agent_desktop_constructor.app.core.models.agent_build_mode import AgentBuildMode
from agent_desktop_constructor.core.models.llm_config import LLMConfig

TRUE_ENV_VALUES = {"1", "true", "yes", "да"}


class AppConfig(BaseModel):
    """Единая конфигурация сборки приложения."""

    app_name: str = "Конструктор ИИ-агентов"
    run_mode: AppRunMode = AppRunMode.FAKE
    agent_build_mode: AgentBuildMode = AgentBuildMode.LLM_SUPERVISED
    database_path: str = "./data/agents.db"
    tools_catalog_path: str | None = None
    use_llm_planner: bool = False
    llm_base_url: str = "http://192.168.1.157:1234"
    llm_model_name: str = "openai/gpt-oss-120b"
    llm_temperature: float = Field(default=0.2, ge=0, le=2)
    llm_timeout_seconds: int = Field(default=120, gt=0)
    com_safe_mode: bool = True
    com_worker_timeout_seconds: int = Field(default=20, gt=0)
    outlook_mail_days: int = Field(default=7, gt=0)
    outlook_mail_max_results: int = Field(default=10, gt=0)
    outlook_calendar_days_forward: int = Field(default=7, gt=0)
    outlook_calendar_max_results: int = Field(default=10, gt=0)

    @field_validator(
        "app_name",
        "database_path",
        "llm_base_url",
        "llm_model_name",
    )
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        """Проверить, что обязательные строковые поля заполнены."""
        if not value.strip():
            raise ValueError("Поле не должно быть пустым")
        return value

    def to_llm_config(self) -> LLMConfig:
        """Преобразовать AppConfig в LLMConfig."""
        return LLMConfig(
            base_url=self.llm_base_url,
            model_name=self.llm_model_name,
            temperature=self.llm_temperature,
            timeout_seconds=self.llm_timeout_seconds,
        )


def load_app_config_from_env() -> AppConfig:
    """Загрузить AppConfig из переменных окружения с дефолтами."""
    values: dict[str, Any] = {}
    if run_mode := os.environ.get("AGENT_APP_RUN_MODE"):
        try:
            values["run_mode"] = AppRunMode(run_mode.strip())
        except ValueError as exc:
            allowed = ", ".join(mode.value for mode in AppRunMode)
            raise ValueError(
                "Некорректный AGENT_APP_RUN_MODE: "
                f"{run_mode!r}. Допустимые значения: {allowed}"
            ) from exc

    if build_mode := os.environ.get("AGENT_APP_AGENT_BUILD_MODE"):
        try:
            values["agent_build_mode"] = AgentBuildMode(build_mode.strip())
        except ValueError as exc:
            allowed = ", ".join(mode.value for mode in AgentBuildMode)
            raise ValueError(
                "Некорректный AGENT_APP_AGENT_BUILD_MODE: "
                f"{build_mode!r}. Допустимые значения: {allowed}"
            ) from exc

    _set_if_present(values, "database_path", "AGENT_APP_DATABASE_PATH")
    _set_if_present(values, "llm_base_url", "AGENT_APP_LLM_BASE_URL")
    _set_if_present(values, "llm_model_name", "AGENT_APP_LLM_MODEL_NAME")
    _set_bool_if_present(values, "use_llm_planner", "AGENT_APP_USE_LLM_PLANNER")
    _set_bool_if_present(values, "com_safe_mode", "AGENT_APP_COM_SAFE_MODE")
    _set_int_if_present(
        values,
        "com_worker_timeout_seconds",
        "AGENT_APP_COM_WORKER_TIMEOUT_SECONDS",
    )

    try:
        return AppConfig(**values)
    except ValidationError as exc:
        raise ValueError(f"Некорректная конфигурация приложения: {exc}") from exc


def _set_if_present(values: dict[str, Any], field_name: str, env_name: str) -> None:
    """Перенести env var в values, если она задана."""
    env_value = os.environ.get(env_name)
    if env_value is not None:
        values[field_name] = env_value


def _set_bool_if_present(values: dict[str, Any], field_name: str, env_name: str) -> None:
    """Прочитать boolean env var."""
    env_value = os.environ.get(env_name)
    if env_value is not None:
        values[field_name] = env_value.strip().casefold() in TRUE_ENV_VALUES


def _set_int_if_present(values: dict[str, Any], field_name: str, env_name: str) -> None:
    """Прочитать integer env var."""
    env_value = os.environ.get(env_name)
    if env_value is not None:
        try:
            values[field_name] = int(env_value)
        except ValueError as exc:
            raise ValueError(f"{env_name} должен быть целым числом") from exc

