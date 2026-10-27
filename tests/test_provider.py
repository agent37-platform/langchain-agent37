"""Verify the installed CLI entry point with the real Deep Agents Code registry."""

import importlib.util

import pytest

from langchain_agent37 import Agent37Sandbox

pytestmark = [
    pytest.mark.cli,
    pytest.mark.skipif(
        importlib.util.find_spec("deepagents_code") is None,
        reason="Install the cli extra on Python 3.14",
    ),
]


def test_registry_discovers_provider_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    from deepagents_code.integrations.sandbox_config import SandboxConfig
    from deepagents_code.integrations.sandbox_registry import SandboxRegistry

    monkeypatch.delenv("AGENT37_API_KEY", raising=False)
    monkeypatch.delenv("DEEPAGENTS_CODE_AGENT37_API_KEY", raising=False)
    registry = SandboxRegistry(config=SandboxConfig())
    assert "agent37" in registry.available_providers()
    metadata = registry.provider_metadata("agent37")
    assert metadata.working_dir == "/workspace"
    assert metadata.supports_sandbox_id
    assert not metadata.supports_snapshot_name
    with pytest.raises(ValueError, match="AGENT37_API_KEY"):
        registry.create_provider("agent37").get_or_create()


@pytest.mark.integration
def test_cli_create_attach_delete_and_not_found() -> None:
    from deepagents_code.integrations.sandbox_config import SandboxConfig
    from deepagents_code.integrations.sandbox_factory import create_sandbox
    from deepagents_code.integrations.sandbox_provider import SandboxNotFoundError
    from deepagents_code.integrations.sandbox_registry import SandboxRegistry

    registry = SandboxRegistry(config=SandboxConfig())
    provider = registry.create_provider("agent37")
    backend = provider.get_or_create()
    try:
        assert isinstance(backend, Agent37Sandbox)
        assert backend.execute("printf cli").output == "cli"
        backend._request("POST", f"/v1/instances/{backend.id}/stop", json={})
        attached = provider.get_or_create(sandbox_id=backend.id)
        try:
            assert attached.execute("printf reconnected").output == "reconnected"
        finally:
            attached.close()
    finally:
        provider.delete(sandbox_id=backend.id)
        backend.close()
    provider.delete(sandbox_id=backend.id)
    with pytest.raises(SandboxNotFoundError):
        provider.get_or_create(sandbox_id=backend.id)
    with create_sandbox("agent37") as managed:
        assert managed.execute("printf managed").output == "managed"
        managed_id = managed.id
    with pytest.raises(SandboxNotFoundError):
        provider.get_or_create(sandbox_id=managed_id)
