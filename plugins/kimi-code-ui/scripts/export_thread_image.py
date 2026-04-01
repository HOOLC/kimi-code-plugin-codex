#!/usr/bin/env python3
"""Export an image from the current Codex thread to a local file."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


DATA_URL_RE = re.compile(r"^data:(image/[^;]+);base64,(.+)$", re.DOTALL)
DEFAULT_PROTOCOL_VERSION = 2
DEFAULT_TIMEOUT_SECONDS = 30
CLIENT_INFO = {"name": "kimi-code-ui-export-thread-image", "version": "0"}
IMAGE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export an image from Codex app-server thread history."
    )
    parser.add_argument(
        "--thread-id",
        default=os.environ.get("CODEX_THREAD_ID", ""),
        help="Codex thread id. Defaults to CODEX_THREAD_ID.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional destination file path. Defaults to a temp file.",
    )
    parser.add_argument(
        "--pick",
        choices=("latest", "first"),
        default="latest",
        help="Which image from thread history to export.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Timeout for app-server requests.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON instead of only the output path.",
    )
    return parser.parse_args()


def initialize_app_server(timeout_seconds: float) -> subprocess.Popen[str]:
    proc = subprocess.Popen(
        ["codex", "app-server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    send_request(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": DEFAULT_PROTOCOL_VERSION,
                "clientInfo": CLIENT_INFO,
            },
        },
    )
    read_response(proc, expect_id=1, timeout_seconds=timeout_seconds)
    return proc


def send_request(proc: subprocess.Popen[str], payload: dict[str, Any]) -> None:
    if proc.stdin is None:
        raise RuntimeError("app-server stdin is unavailable")
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()


def read_response(
    proc: subprocess.Popen[str],
    *,
    expect_id: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    if proc.stdout is None:
        raise RuntimeError("app-server stdout is unavailable")

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("id") != expect_id:
            continue
        if "error" in payload:
            message = payload["error"].get("message", "unknown app-server error")
            raise RuntimeError(message)
        return payload
    raise TimeoutError(f"timed out waiting for app-server response {expect_id}")


def read_thread(proc: subprocess.Popen[str], thread_id: str, timeout_seconds: float) -> dict[str, Any]:
    send_request(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "thread/read",
            "params": {
                "threadId": thread_id,
                "includeTurns": True,
            },
        },
    )
    response = read_response(proc, expect_id=2, timeout_seconds=timeout_seconds)
    return response["result"]["thread"]


def collect_images(thread: dict[str, Any]) -> list[dict[str, str]]:
    images: list[dict[str, str]] = []
    for turn in thread.get("turns", []):
        for item in turn.get("items", []):
            if item.get("type") != "userMessage":
                continue
            for content in item.get("content", []):
                content_type = content.get("type")
                if content_type == "image" and content.get("url"):
                    images.append({"type": "image", "value": str(content["url"])})
                elif content_type in {"localImage", "local_image"} and content.get("path"):
                    images.append({"type": "localImage", "value": str(content["path"])})
    return images


def export_image(image: dict[str, str], thread_id: str, output: str) -> tuple[Path, str]:
    source_type = image["type"]
    value = image["value"]
    if source_type == "image":
        return export_data_url(value, thread_id=thread_id, output=output), "image"
    return export_local_image(Path(value), thread_id=thread_id, output=output), "localImage"


def export_data_url(data_url: str, *, thread_id: str, output: str) -> Path:
    match = DATA_URL_RE.match(data_url)
    if match is None:
        raise ValueError("image content is not a supported base64 data URL")

    mime_type = match.group(1)
    encoded = match.group(2)
    data = base64.b64decode(encoded)
    extension = extension_for_mime(mime_type)
    path = resolve_output_path(thread_id=thread_id, output=output, extension=extension)
    path.write_bytes(data)
    return path


def export_local_image(source: Path, *, thread_id: str, output: str) -> Path:
    if not source.exists():
        raise FileNotFoundError(f"local image does not exist: {source}")

    extension = source.suffix or ".bin"
    path = resolve_output_path(thread_id=thread_id, output=output, extension=extension)
    shutil.copyfile(source, path)
    return path


def extension_for_mime(mime_type: str) -> str:
    if mime_type in IMAGE_EXTENSIONS:
        return IMAGE_EXTENSIONS[mime_type]
    return mimetypes.guess_extension(mime_type) or ".bin"


def resolve_output_path(*, thread_id: str, output: str, extension: str) -> Path:
    if output:
        return Path(output).expanduser().resolve()
    return Path(tempfile.gettempdir()) / f"codex-thread-image-{thread_id}{extension}"


def main() -> int:
    args = parse_args()
    if not args.thread_id:
        raise SystemExit("--thread-id is required when CODEX_THREAD_ID is not set")

    proc = initialize_app_server(timeout_seconds=args.timeout_seconds)
    try:
        thread = read_thread(proc, thread_id=args.thread_id, timeout_seconds=args.timeout_seconds)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()

    images = collect_images(thread)
    if not images:
        raise SystemExit("No image inputs found in thread history.")

    selected = images[-1] if args.pick == "latest" else images[0]
    path, source_type = export_image(selected, thread_id=args.thread_id, output=args.output)

    if args.json:
        payload = {
            "path": str(path),
            "source_type": source_type,
        }
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
