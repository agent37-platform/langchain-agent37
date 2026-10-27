"""Run the upstream contract and Agent37-specific behavior against real instances."""

import asyncio
import os
import uuid
from collections.abc import Iterator

import httpx
import pytest
from deepagents import create_deep_agent
from langchain_tests.integration_tests import SandboxIntegrationTests

from langchain_agent37 import Agent37Sandbox

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def sandbox() -> Iterator[Agent37Sandbox]:
    with Agent37Sandbox(create_options={"name": "langchain-agent37-test"}) as backend:
        yield backend


class TestAgent37Standard(SandboxIntegrationTests):
    @pytest.fixture(scope="class")
    def sandbox(self) -> Iterator[Agent37Sandbox]:
        with Agent37Sandbox(create_options={"name": "langchain-agent37-contract"}) as backend:
            yield backend


def test_binary_files_partial_errors_and_shell_safe_paths(sandbox: Agent37Sandbox) -> None:
    directory = f"/workspace/test-{uuid.uuid4().hex}"
    path = f"{directory}/space ' quote $(touch SHOULD_NOT_EXIST) ; unicode-日.bin"
    content = bytes(range(256)) * 4097
    results = sandbox.upload_files([(path, content), ("relative.bin", b"bad"), (directory, b"bad")])
    assert results[0].error is None
    assert results[1].error == "invalid_path"
    assert results[2].error == "is_directory"
    downloads = sandbox.download_files([path, f"{directory}/absent", directory, "relative.bin"])
    assert downloads[0].content == content
    assert downloads[1].error == "file_not_found"
    assert downloads[2].error == "is_directory"
    assert downloads[3].error == "invalid_path"
    assert sandbox.execute("test ! -e SHOULD_NOT_EXIST").exit_code == 0


def test_command_exit_stderr_cwd_and_timeout(sandbox: Agent37Sandbox) -> None:
    result = sandbox.execute("printf out; printf err >&2; exit 7")
    assert result.exit_code == 7
    assert result.output == "outerr"
    assert sandbox.execute("pwd").output.strip() == "/workspace"
    marker = f"/workspace/timeout-{uuid.uuid4().hex}"
    result = sandbox.execute(f"sleep 3; touch {marker}", timeout=1)
    assert result.exit_code == 124
    assert sandbox.execute(f"sleep 3; test ! -e {marker}").exit_code == 0


@pytest.mark.asyncio
async def test_async_parallel_operations(sandbox: Agent37Sandbox) -> None:
    results = await asyncio.gather(*(sandbox.aexecute(f"printf {i}") for i in range(3)))
    assert [r.output for r in results] == ["0", "1", "2"]
    path = f"/workspace/async-{uuid.uuid4().hex}.txt"
    uploads = await sandbox.aupload_files([(path, b"async bytes")])
    assert uploads[0].error is None
    assert (await sandbox.adownload_files([path]))[0].content == b"async bytes"


def test_attached_context_preserves_instance_and_files(sandbox: Agent37Sandbox) -> None:
    path = f"/workspace/persist-{uuid.uuid4().hex}.txt"
    with Agent37Sandbox(instance_id=sandbox.id) as attached:
        assert attached.upload_files([(path, b"persisted")])[0].error is None
    assert sandbox.download_files([path])[0].content == b"persisted"


@pytest.mark.asyncio
async def test_glob_current_absolute_file_only_contract(sandbox: Agent37Sandbox) -> None:
    directory = f"/workspace/glob-{uuid.uuid4().hex}"
    assert sandbox.execute(f"mkdir -p {directory}/nested").exit_code == 0
    for path in ["a.py", "b.txt", ".hidden", "nested/c.py"]:
        assert sandbox.write(f"{directory}/{path}", "content").error is None
    result = sandbox.glob("*.py", path=directory)
    assert result.error is None
    assert sorted(m["path"] for m in result.matches) == [
        f"{directory}/a.py",
        f"{directory}/nested/c.py",
    ]
    result = await sandbox.aglob(".*", path=directory)
    assert result.error is None
    assert [m["path"] for m in result.matches] == [f"{directory}/.hidden"]
    result = sandbox.glob("*", path=directory)
    assert result.error is None
    assert all(not m["is_dir"] for m in result.matches)


def test_write_current_overwrite_contract(sandbox: Agent37Sandbox) -> None:
    path = f"/workspace/overwrite-{uuid.uuid4().hex}.txt"
    assert sandbox.write(path, "first").error is None
    assert sandbox.write(path, "second").error is None
    assert sandbox.download_files([path])[0].content == b"second"


def test_created_context_cleans_up_after_exception() -> None:
    instance_id = ""
    with pytest.raises(RuntimeError, match="application failure"):
        with Agent37Sandbox(create_options={"name": "langchain-agent37-cleanup"}) as backend:
            instance_id = backend.id
            raise RuntimeError("application failure")
    with Agent37Sandbox(instance_id=instance_id) as attached:
        with pytest.raises(httpx.HTTPStatusError) as error:
            attached.execute("true")
        assert error.value.response.status_code == 404


@pytest.mark.slow
def test_quiet_command_keeps_connection_alive(sandbox: Agent37Sandbox) -> None:
    result = sandbox.execute("sleep 200; printf survived", timeout=220)
    assert result.exit_code == 0
    assert result.output == "survived"


@pytest.mark.llm
@pytest.mark.asyncio
async def test_real_deep_agent_sync_and_async(sandbox: Agent37Sandbox) -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.fail("OPENAI_API_KEY is required for the LLM test")
    agent = create_deep_agent(model="openai:gpt-5.5", backend=sandbox)
    path = f"/workspace/agent-{uuid.uuid4().hex}.txt"
    response = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"Use write_file to write exactly 'agent37-live-test' to {path}. "
                        f"Then use execute to run cat {path}. Do both tools now."
                    ),
                }
            ]
        }
    )
    assert any(getattr(m, "name", "") == "execute" for m in response["messages"])
    assert sandbox.download_files([path])[0].content == b"agent37-live-test"
    response = await agent.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"Read {path} using read_file. Then use edit_file to replace "
                        "agent37-live-test with agent37-async-test. Do both tools now."
                    ),
                }
            ]
        }
    )
    assert any(getattr(m, "name", "") == "edit_file" for m in response["messages"])
    assert sandbox.download_files([path])[0].content == b"agent37-async-test"
