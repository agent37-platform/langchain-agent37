"""Reject invalid configuration before creating a billable instance."""

import pytest

from langchain_agent37 import Agent37Sandbox


@pytest.mark.parametrize("timeout", [0, -1, 841, True, 1.5, "120"])
def test_invalid_timeout(timeout: object) -> None:
    with pytest.raises(ValueError, match="timeout"):
        Agent37Sandbox(api_key="unused", timeout=timeout)  # type: ignore[arg-type]


@pytest.mark.parametrize("path", ["relative", "", "/workspace\x00bad"])
def test_invalid_workdir(path: str) -> None:
    with pytest.raises(ValueError, match="workdir"):
        Agent37Sandbox(api_key="unused", workdir=path)


def test_explicit_empty_api_key_never_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT37_API_KEY", "must-not-be-used")
    with pytest.raises(ValueError, match="AGENT37_API_KEY"):
        Agent37Sandbox(api_key="")
