# langchain-agent37

Run LangChain Deep Agents commands and file operations in [Agent37 Cloud](https://www.agent37.com) sandboxes.

This package implements Deep Agents' `BaseSandbox` over Agent37's public REST API. Your agent and model client run in your application. Shell commands, file reads, writes, edits, searches, uploads, and downloads run in the remote instance.

## Install

Requires Python 3.11 or newer.

```bash
pip install langchain-agent37
export AGENT37_API_KEY=sk_live_...
```

Create a key and fund your workspace at [Agent37 Cloud](https://www.agent37.com/dashboard/cloud/api-keys). Instances use your workspace balance while running; delete them when finished.

## Use with Deep Agents

Install the model provider you use, then pass the sandbox as the backend:

```bash
pip install langchain-openai
export OPENAI_API_KEY=...
```

```python
from deepagents import create_deep_agent
from langchain_agent37 import Agent37Sandbox

with Agent37Sandbox() as sandbox:
    agent = create_deep_agent(model="openai:gpt-5.5", backend=sandbox)
    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Write /workspace/hello.py, run it, and show me its output.",
                }
            ]
        }
    )
    print(result["messages"][-1].content)
```

The context manager deletes the instance on exit, including when your code raises an exception. It creates the plain `agent37-base` template by default. No agent harness or gateway is required inside the instance.

## Commands and files

```python
with Agent37Sandbox(timeout=120) as sandbox:
    print(sandbox.execute("python3 --version").output)
    sandbox.write("/workspace/hello.py", "print('hello from Agent37')\n")
    print(sandbox.execute("python3 hello.py").output)
    print(sandbox.read("/workspace/hello.py"))

    uploads = sandbox.upload_files([("/workspace/input.bin", b"\x00\x01\x02")])
    assert uploads[0].error is None
    downloads = sandbox.download_files(["/workspace/input.bin"])
    assert downloads[0].content == b"\x00\x01\x02"
```

Commands run as root in `/workspace` by default. Set `workdir` to another absolute sandbox path. Each command uses a fresh shell; filesystem changes persist, but `cd` and exported variables do not carry into the next command. Set instance environment variables with `create_options={"env": {...}}`.

`execute()` returns Deep Agents' `ExecuteResponse`: combined stdout and stderr, `exit_code`, and `truncated`. Nonzero command exits are normal responses. HTTP/platform failures raise `httpx.HTTPError`, and the package never retries a command automatically.

The default command timeout is 120 seconds. Override it with `execute(command, timeout=300)` or the constructor's `timeout`. Supported values are 1 to 840 seconds. GNU `timeout` terminates the command and its process group when the deadline expires, returning 124 (or 137 if force-killed). An HTTP/network failure is different: the remote command might still be running.

File transfers use chunked exec calls and support binary content larger than the exec output limit. Uploads replace the destination only after all chunks arrive. Batch operations return a result for each path, including errors such as `file_not_found`, `permission_denied`, `is_directory`, and `invalid_path`. Use absolute paths for uploads and downloads.

Async operations (`aexecute`, `aread`, `awrite`, `aedit`, `als`, `agrep`, `aglob`, `aupload_files`, and `adownload_files`) are provided by Deep Agents using worker threads. Use `agent.ainvoke(...)` for an async agent.

## Reuse an instance

```python
sandbox = Agent37Sandbox()
instance_id = sandbox.id
sandbox.write("/workspace/notes.txt", "Keep this for the next run.\n")
sandbox.close()  # Close the HTTP connection; keep the instance and its files.

with Agent37Sandbox(instance_id=instance_id) as attached:
    print(attached.read("/workspace/notes.txt"))
# An attached instance is left running when the context exits.

attached = Agent37Sandbox(instance_id=instance_id)
attached.destroy()  # Explicitly delete it when finished.
```

Attached instances must be running or sleeping. Exec wakes a sleeping instance automatically. Start a stopped instance through the [Agent37 API](https://www.agent37.com/docs/agents-api/instances/start) first. `close()` never deletes an instance; `destroy()` does, including an attached one. Deep Agents' `delete(path)` deletes a file, not the instance.

## Instance options

```python
with Agent37Sandbox(
    template="agent37-base",
    create_options={
        "resources": {"cpu": 2, "memory": 4, "disk": 4},
        "auto_sleep": True,
        "idle_timeout_seconds": 900,
        "env": {"PROJECT_NAME": "example"},
    },
) as sandbox:
    print(sandbox.execute("echo $PROJECT_NAME").output)
```

`create_options` passes JSON fields to [Create an instance](https://www.agent37.com/docs/agents-api/instances/create). Custom templates must include Python 3, a POSIX shell, and GNU coreutils. The sandbox is the isolation boundary: commands run with root access to that instance, and `workdir` does not restrict access to other paths inside it.

## Deep Agents Code

The optional CLI integration requires Python 3.14, matching the current Deep Agents Code release:

```bash
uv tool install --python 3.14 --with langchain-agent37 deepagents-code
export AGENT37_API_KEY=sk_live_...
dcode --sandbox agent37
```

Or install both into one Python 3.14 environment with `pip install 'langchain-agent37[cli]'`.

The package registers `agent37` through the `deepagents_code.sandbox_providers` entry point. Use `--sandbox-id <instance-id>` to reuse an instance. The CLI starts a stopped instance when reconnecting, and manages deletion of instances it creates. `DEEPAGENTS_CODE_AGENT37_API_KEY` is also supported through the CLI's environment resolver.

## Development

```bash
uv sync --python 3.14 --extra cli
uv run --extra cli ruff check .
uv run --extra cli mypy
uv run --extra cli pytest -m 'not integration'
AGENT37_API_KEY=sk_live_... uv run --extra cli pytest -m 'integration and not llm and not slow'
AGENT37_API_KEY=sk_live_... OPENAI_API_KEY=... uv run --extra cli pytest -m llm
AGENT37_API_KEY=sk_live_... uv run --extra cli pytest -m slow
uv build
uv run --extra cli twine check dist/*
```

Integration tests run LangChain's sandbox contract suite against real Agent37 instances and delete test instances afterward. They spend real workspace balance. No emulators or mocked API responses are used.

Seven upstream assertions are marked as strict expected failures: the suite expects [relative paths and rejected file overwrites](https://github.com/langchain-ai/langchain/issues/41511), plus [directory matches](https://github.com/langchain-ai/langchain/issues/39948). Current Deep Agents returns absolute paths and files only, and allows overwrites. Separate live tests verify these current contracts. These markers must be removed when the upstream tests are corrected; an unexpected pass fails CI.

## Releases

The `release.yml` GitHub Actions workflow builds and publishes a tagged release using PyPI Trusted Publishing and the `pypi` environment. No PyPI token is needed. The tag must match the package version, for example `v0.1.0`.
