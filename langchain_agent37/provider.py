"""Discoverable Agent37 provider for Deep Agents Code (optional cli extra)."""

from __future__ import annotations

from typing import Any

import httpx
from deepagents_code.integrations.sandbox_provider import (
    SandboxInstallHint,
    SandboxNotFoundError,
    SandboxProvider,
    SandboxProviderMetadata,
)
from deepagents_code.model_config import resolve_env_var

from langchain_agent37.sandbox import DEFAULT_WORKDIR, Agent37Sandbox


class Agent37Provider(SandboxProvider):
    """Create, reconnect, and delete Agent37 instances for Deep Agents Code."""

    @property
    def metadata(self) -> SandboxProviderMetadata:
        return SandboxProviderMetadata(
            name="agent37",
            working_dir=DEFAULT_WORKDIR,
            install=SandboxInstallHint(kind="package", name="langchain-agent37"),
            supports_sandbox_id=True,
            supports_snapshot_name=False,
            backend_module="langchain_agent37",
        )

    def get_or_create(
        self,
        *,
        sandbox_id: str | None = None,
        **kwargs: Any,
    ) -> Agent37Sandbox:
        api_key = resolve_env_var("AGENT37_API_KEY")
        if not api_key:
            raise ValueError("Set AGENT37_API_KEY or DEEPAGENTS_CODE_AGENT37_API_KEY")
        sandbox = Agent37Sandbox(instance_id=sandbox_id, api_key=api_key, **kwargs)
        try:
            if sandbox_id:
                instance = sandbox._request("GET", f"/v1/instances/{sandbox_id}")
                if instance["status"] == "stopped":
                    sandbox._request("POST", f"/v1/instances/{sandbox_id}/start", json={})
            return sandbox
        except httpx.HTTPError as exc:
            sandbox.close()
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
                raise SandboxNotFoundError(str(sandbox_id)) from exc
            raise

    def delete(self, *, sandbox_id: str, **kwargs: Any) -> None:
        api_key = resolve_env_var("AGENT37_API_KEY")
        if not api_key:
            raise ValueError("Set AGENT37_API_KEY or DEEPAGENTS_CODE_AGENT37_API_KEY")
        sandbox = Agent37Sandbox(instance_id=sandbox_id, api_key=api_key, **kwargs)
        try:
            sandbox.destroy()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
        finally:
            sandbox.close()
