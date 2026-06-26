"""Application service for agent lifecycle operations."""

from __future__ import annotations

from agent_desktop_constructor.builder.agent_builder import AgentBuilder
from agent_desktop_constructor.core.models.agent_spec import AgentSpec
from agent_desktop_constructor.core.models.runtime_state import AgentRuntimeState
from agent_desktop_constructor.runtime.simple_runtime import SimpleAgentRuntime
from agent_desktop_constructor.storage.repositories import (
    AgentRepository,
    AgentRunRepository,
    AuditLogRepository,
)


class AgentApplicationService:
    """Сервисный слой приложения для UI, CLI и будущих application workflows."""

    def __init__(
        self,
        agent_builder: AgentBuilder,
        runtime: SimpleAgentRuntime,
        agent_repository: AgentRepository | None = None,
        run_repository: AgentRunRepository | None = None,
        audit_repository: AuditLogRepository | None = None,
    ) -> None:
        """Создать сервис с repository или memory-only режимом."""
        self._agent_builder = agent_builder
        self._runtime = runtime
        self._agent_repository = agent_repository
        self._run_repository = run_repository
        self._audit_repository = audit_repository
        self._memory_agents: dict[str, AgentSpec] = {}
        self._memory_audit_logs: list[dict] = []
        self._audit_warnings: list[str] = []

    @property
    def memory_audit_logs(self) -> list[dict]:
        """Вернуть in-memory audit logs для тестов и CLI diagnostics."""
        return list(self._memory_audit_logs)

    @property
    def audit_warnings(self) -> list[str]:
        """Вернуть предупреждения о сбоях audit repository."""
        return list(self._audit_warnings)

    def build_preview(self, user_request: str) -> AgentSpec:
        """Построить AgentSpec из запроса без сохранения и запуска."""
        normalized_request = user_request.strip()
        if not normalized_request:
            raise ValueError("user_request не должен быть пустым")
        return self._agent_builder.build_from_request(normalized_request)

    def save_agent(self, agent_spec: AgentSpec) -> None:
        """Сохранить AgentSpec в repository или memory-only storage."""
        if self._agent_repository is not None:
            self._agent_repository.save_agent(agent_spec)
        else:
            self._memory_agents[agent_spec.agent_id] = agent_spec

        self._add_audit(
            action="agent.saved",
            details={"agent_id": agent_spec.agent_id, "name": agent_spec.name},
        )

    def create_agent_from_request(
        self,
        user_request: str,
        save: bool = True,
    ) -> AgentSpec:
        """Создать AgentSpec из запроса и опционально сохранить."""
        agent_spec = self.build_preview(user_request)
        if save:
            self.save_agent(agent_spec)
        return agent_spec

    def get_agent(self, agent_id: str) -> AgentSpec:
        """Вернуть AgentSpec по agent_id."""
        if self._agent_repository is not None:
            return self._agent_repository.get_agent(agent_id)

        if agent_id not in self._memory_agents:
            raise ValueError(f"Агент с agent_id={agent_id!r} не найден")
        return self._memory_agents[agent_id]

    def list_agents(self) -> list[AgentSpec]:
        """Вернуть сохранённых агентов."""
        if self._agent_repository is not None:
            return self._agent_repository.list_agents()
        return list(self._memory_agents.values())

    def run_agent(
        self,
        agent_id: str,
        initial_variables: dict | None = None,
    ) -> AgentRuntimeState:
        """Запустить сохранённого агента."""
        agent_spec = self.get_agent(agent_id)
        self._add_audit(
            action="agent.run_started",
            details={"agent_id": agent_spec.agent_id},
        )
        state = self._runtime.run(agent_spec, initial_variables)
        self._add_audit(
            action="agent.run_finished",
            details={
                "agent_id": agent_spec.agent_id,
                "status": state.status.value,
            },
            run_id=state.run_id,
        )
        return state

    def run_agent_spec(
        self,
        agent_spec: AgentSpec,
        initial_variables: dict | None = None,
    ) -> AgentRuntimeState:
        """Запустить AgentSpec без сохранения."""
        self._add_audit(
            action="agent.run_started",
            details={"agent_id": agent_spec.agent_id},
        )
        state = self._runtime.run(agent_spec, initial_variables)
        self._add_audit(
            action="agent.run_finished",
            details={
                "agent_id": agent_spec.agent_id,
                "status": state.status.value,
            },
            run_id=state.run_id,
        )
        return state

    def resume_run(
        self,
        agent_spec: AgentSpec,
        state: AgentRuntimeState,
        approved: bool,
        comment: str | None = None,
    ) -> AgentRuntimeState:
        """Продолжить запуск после HumanApproval."""
        resumed_state = self._runtime.resume(agent_spec, state, approved, comment)
        self._add_audit(
            action="human.approval_approved" if approved else "human.approval_rejected",
            details={
                "agent_id": agent_spec.agent_id,
                "approved": approved,
                "comment": comment,
            },
            run_id=resumed_state.run_id,
        )
        return resumed_state

    def _add_audit(
        self,
        action: str,
        details: dict,
        run_id: str | None = None,
    ) -> None:
        """Добавить audit log, не роняя основной процесс при ошибке audit."""
        payload = {
            "action": action,
            "details": details,
            "run_id": run_id,
        }
        if self._audit_repository is None:
            self._memory_audit_logs.append(payload)
            return

        try:
            self._audit_repository.add_log(
                action=action,
                details=details,
                run_id=run_id,
            )
        except Exception as exc:
            self._audit_warnings.append(f"Ошибка audit log: {exc}")

