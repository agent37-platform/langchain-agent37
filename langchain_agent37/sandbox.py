"""Deep Agents sandbox operations over the public Agent37 REST API."""

from __future__ import annotations

import base64
import json
import os
import re
import shlex
import socket
import uuid
from types import TracebackType
from typing import Any, Self

import httpx
from deepagents.backends.protocol import ExecuteResponse, FileDownloadResponse, FileUploadResponse
from deepagents.backends.sandbox import BaseSandbox

DEFAULT_WORKDIR = "/workspace"
_CHUNK_BYTES = 48 * 1024

_FILE_SCRIPT = """
import base64, errno, json, os, sys
args = json.loads(sys.argv[1])
try:
    path = args['path']
    if not path.startswith('/') or '\\x00' in path:
        print(json.dumps({'error': 'invalid_path'}))
    elif args['op'] == 'upload':
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(args['temp'], 'wb' if args['offset'] == 0 else 'ab') as f:
            f.write(base64.b64decode(args['content']))
        if args['last']:
            os.replace(args['temp'], path)
        print('{}')
    else:
        with open(path, 'rb') as f:
            f.seek(args['offset'])
            content = f.read(args['size'])
        print(json.dumps({'content': base64.b64encode(content).decode(),
                          'last': len(content) < args['size']}))
except OSError as exc:
    errors = {errno.ENOENT: 'file_not_found', errno.EACCES: 'permission_denied',
              errno.EPERM: 'permission_denied', errno.EISDIR: 'is_directory',
              errno.ENOTDIR: 'invalid_path', errno.ENAMETOOLONG: 'invalid_path'}
    print(json.dumps({'error': errors.get(exc.errno, str(exc))}))
except ValueError:
    print(json.dumps({'error': 'invalid_path'}))
"""


def _http_client() -> httpx.Client:
    options = [(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)]
    for name in ("TCP_KEEPIDLE", "TCP_KEEPALIVE"):
        if hasattr(socket, name):
            options.append((socket.IPPROTO_TCP, getattr(socket, name), 15))
            break
    return httpx.Client(
        transport=httpx.HTTPTransport(socket_options=options),
        timeout=httpx.Timeout(180, connect=15),
    )


def _validate_timeout(timeout: int) -> int:
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 840:
        raise ValueError("timeout must be an integer between 1 and 840 seconds")
    return timeout


class Agent37Sandbox(BaseSandbox):
    """Create an Agent37 instance, or connect to an existing instance by ID.

    A context manager deletes an instance it created, and leaves an attached
    instance running. Outside a context manager, call ``destroy()`` to delete
    the instance or ``close()`` to release only the HTTP connection.

    ``create_options`` accepts the public create endpoint's JSON fields, such
    as ``resources``, ``env``, ``auto_sleep``, and ``type``. A custom template
    must include Python 3 and GNU coreutils. All file paths are sandbox paths.
    """

    enable_capture_offload = True

    def __init__(
        self,
        instance_id: str | None = None,
        *,
        api_key: str | None = None,
        template: str = "agent37-base",
        create_options: dict[str, Any] | None = None,
        workdir: str = DEFAULT_WORKDIR,
        timeout: int = 120,
        base_url: str = "https://api.agent37.com",
        exec_url: str = "https://sandbox.agent37.app",
    ) -> None:
        key = api_key if api_key is not None else os.environ.get("AGENT37_API_KEY")
        if not key:
            raise ValueError("Set AGENT37_API_KEY or pass api_key")
        self._api_key = key
        if instance_id is not None and not re.fullmatch(r"[a-z0-9]+", instance_id):
            raise ValueError("instance_id must contain only lowercase letters and digits")
        if not workdir.startswith("/") or "\x00" in workdir:
            raise ValueError("workdir must be an absolute sandbox path without null bytes")
        if instance_id is not None and create_options:
            raise ValueError("create_options cannot be used with an existing instance")
        self.workdir = workdir
        self.timeout = _validate_timeout(timeout)
        self._base_url = base_url.rstrip("/")
        self._exec_url = exec_url.rstrip("/")
        self._owns_instance = instance_id is None
        self._destroyed = False
        self._client = _http_client()
        try:
            if instance_id is None:
                instance = self._request(
                    "POST", "/v1/instances", json={"template": template, **(create_options or {})}
                )
                self._id: str = instance["id"]
            else:
                self._id = instance_id
        except BaseException:
            self._client.close()
            raise

    @property
    def id(self) -> str:
        """Agent37 instance ID, reusable when connecting later."""
        return self._id

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        execution: bool = False,
        timeout: int = 180,
    ) -> dict[str, Any]:
        origin = self._exec_url if execution else self._base_url
        headers = (
            {"X-Agent37-Key": self._api_key}
            if execution
            else {"Authorization": f"Bearer {self._api_key}"}
        )
        response = self._client.request(
            method,
            origin + path,
            json=json,
            headers=headers,
            timeout=httpx.Timeout(timeout, connect=15),
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    def _exec(self, command: str, timeout: int = 120) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/instances/{self.id}/exec",
            execution=True,
            json={"command": command, "user": "root"},
            timeout=timeout + 45,
        )

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        """Run a shell command in the sandbox, killing it when its timeout expires.

        GNU timeout returns exit code 124 on expiry (137 if it must force-kill).
        Platform/HTTP failures raise ``httpx.HTTPError``; commands are never retried.
        """
        seconds = _validate_timeout(self.timeout if timeout is None else timeout)
        directory = shlex.quote(self.workdir)
        result = self._exec(
            f"mkdir -p {directory} && cd {directory} && "
            f"timeout --kill-after=5s {seconds}s sh -c {shlex.quote(command)}",
            seconds,
        )
        return ExecuteResponse(
            output=result["stdout"] + result["stderr"],
            exit_code=result["exit_code"],
            truncated=result["truncated"],
        )

    def _file_op(self, args: dict[str, Any]) -> dict[str, Any]:
        result = self._exec(
            f"python3 -c {shlex.quote(_FILE_SCRIPT)} {shlex.quote(json.dumps(args))}"
        )
        if result["exit_code"] != 0 or result["truncated"]:
            raise RuntimeError(result["stderr"] or "File transfer failed or was truncated")
        data: dict[str, Any] = json.loads(result["stdout"])
        return data

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload binary files in chunks; replace each destination only after success."""
        responses = []
        for path, content in files:
            error = None
            temporary = f"{path}.agent37-{uuid.uuid4().hex}.tmp"
            try:
                for offset in range(0, max(1, len(content)), _CHUNK_BYTES):
                    data = self._file_op(
                        {
                            "op": "upload",
                            "path": path,
                            "temp": temporary,
                            "offset": offset,
                            "content": base64.b64encode(
                                content[offset : offset + _CHUNK_BYTES]
                            ).decode(),
                            "last": offset + _CHUNK_BYTES >= len(content),
                        }
                    )
                    error = data.get("error")
                    if error:
                        break
            except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                error = str(exc)
            if error and path.startswith("/") and "\x00" not in path:
                try:
                    self._exec(f"rm -f -- {shlex.quote(temporary)}")
                except httpx.HTTPError:
                    pass
            responses.append(FileUploadResponse(path=path, error=error))
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download binary files in chunks, preserving per-file errors and order."""
        responses = []
        for path in paths:
            content = bytearray()
            error = None
            try:
                while True:
                    data = self._file_op(
                        {
                            "op": "download",
                            "path": path,
                            "offset": len(content),
                            "size": _CHUNK_BYTES,
                        }
                    )
                    error = data.get("error")
                    if error:
                        break
                    content.extend(base64.b64decode(data["content"], validate=True))
                    if data["last"]:
                        break
            except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                error = str(exc)
            responses.append(
                FileDownloadResponse(
                    path=path,
                    content=None if error else bytes(content),
                    error=error,
                )
            )
        return responses

    def close(self) -> None:
        """Release HTTP connections without deleting the instance."""
        self._client.close()

    def destroy(self) -> None:
        """Delete the instance and close connections. This also deletes attached instances."""
        if not self._destroyed:
            self._request("DELETE", f"/v1/instances/{self.id}")
            self._destroyed = True
        self.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            if self._owns_instance:
                self.destroy()
        finally:
            self.close()
