#!/usr/bin/env python3
"""Adapter for bounded frontend/UI tasks executed through kimi-cli."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import subprocess
import threading
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from typing import Sequence


MAX_FILE_CHARS = 12000
TAIL_CHARS = 4000
RETRYABLE_EXIT_CODE = 75


@dataclass(frozen=True)
class FileSnapshot:
    path: Path
    existed: bool
    digest: str | None


@dataclass(frozen=True)
class VerificationResult:
    command: str
    exit_code: int
    stdout_tail: str
    stderr_tail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
        }


@dataclass(frozen=True)
class ProgressEvent:
    type: str
    timestamp: float
    payload: dict[str, object]

    def to_json_line(self) -> str:
        body = {"type": self.type, "timestamp": self.timestamp, **self.payload}
        return json.dumps(body, ensure_ascii=False)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a bounded frontend/UI task through kimi-cli and emit stable results."
    )
    parser.add_argument("--task", required=True, help="Concrete frontend or UI task for Kimi.")
    parser.add_argument(
        "--target-file",
        action="append",
        dest="target_files",
        required=True,
        help="Editable file path. Repeat to allow multiple files.",
    )
    parser.add_argument(
        "--context-file",
        action="append",
        dest="context_files",
        default=[],
        help="Read-only context file path. Repeat to include multiple files.",
    )
    parser.add_argument(
        "--constraint",
        action="append",
        default=[],
        help="Extra design or implementation constraint. Repeatable.",
    )
    parser.add_argument(
        "--reference-image",
        action="append",
        dest="reference_images",
        default=[],
        help="Reference image path for Kimi to inspect directly. Repeatable.",
    )
    parser.add_argument(
        "--verify-cmd",
        action="append",
        default=[],
        help="Verification command to run after a successful Kimi edit. Repeatable.",
    )
    parser.add_argument(
        "--cwd",
        default=".",
        help="Working directory for the Kimi run and path resolution.",
    )
    parser.add_argument("--model", default="", help="Optional Kimi model override.")
    thinking_group = parser.add_mutually_exclusive_group()
    thinking_group.add_argument(
        "--thinking",
        dest="thinking",
        action="store_true",
        help="Enable Kimi thinking mode.",
    )
    thinking_group.add_argument(
        "--no-thinking",
        dest="thinking",
        action="store_false",
        help="Disable Kimi thinking mode.",
    )
    parser.set_defaults(thinking=None)
    parser.add_argument(
        "--max-steps-per-turn",
        type=int,
        default=None,
        help="Optional Kimi max steps override.",
    )
    parser.add_argument(
        "--progress-file",
        default="",
        help="Optional JSONL file path for progress events.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text output.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args: argparse.Namespace | None = None
    try:
        args = parse_args(argv)
        payload = execute(args)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_text_summary(payload))
        return 0 if payload["status"] in {"success", "no_change"} else 1
    except Exception as exc:  # pragma: no cover - defensive entrypoint
        payload = failure_payload(str(exc), cwd=Path.cwd(), task="", kimi_exit_code=1)
        if args is not None and args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        elif argv is not None and "--json" in argv:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(render_text_summary(payload))
        return 1


def execute(args: argparse.Namespace) -> dict[str, object]:
    cwd = Path(args.cwd).expanduser().resolve()
    if not cwd.exists() or not cwd.is_dir():
        raise ValueError(f"--cwd must point to an existing directory: {cwd}")

    if which("kimi") is None:
        return failure_payload("kimi executable not found on PATH.", cwd=cwd, task=args.task)

    target_paths = dedupe_paths(args.target_files, cwd, allow_missing=True)
    context_paths = dedupe_paths(args.context_files, cwd, allow_missing=False)
    reference_image_paths = dedupe_paths(
        args.reference_images,
        cwd,
        allow_missing=False,
        enforce_within_cwd=False,
        missing_label="Reference image",
    )
    progress_path = resolve_progress_path(args.progress_file, cwd)
    progress_writer = ProgressWriter(progress_path)

    progress_writer.emit(
        "run_started",
        {
            "task": args.task,
            "cwd": str(cwd),
            "target_files": [str(path) for path in target_paths],
            "context_files": [str(path) for path in context_paths],
            "reference_images": [str(path) for path in reference_image_paths],
        },
    )

    before = {path: snapshot_file(path) for path in target_paths}
    repo_facts = detect_repo_facts(cwd)
    progress_writer.emit("repo_facts_detected", {"repo_facts": repo_facts})
    prompt = build_prompt(
        task=args.task,
        cwd=cwd,
        target_paths=target_paths,
        context_paths=context_paths,
        reference_image_paths=reference_image_paths,
        constraints=args.constraint,
        repo_facts=repo_facts,
    )

    kimi_result = run_kimi_with_retry(
        prompt=prompt,
        cwd=cwd,
        model=args.model,
        thinking=args.thinking,
        max_steps_per_turn=args.max_steps_per_turn,
        progress_writer=progress_writer,
    )

    file_results = collect_file_results(target_paths, before)
    emit_file_events(file_results, progress_writer)
    changed_files = [
        str(item["path"])
        for item in file_results
        if item["status"] in {"modified", "created"}
    ]
    unchanged_target_files = [
        str(item["path"]) for item in file_results if item["status"] == "unchanged"
    ]

    verification: list[VerificationResult] = []
    if kimi_result["exit_code"] == 0 and changed_files and args.verify_cmd:
        progress_writer.emit("verification_started", {"commands": list(args.verify_cmd)})
        verification = run_verification_commands(args.verify_cmd, cwd)
        for item in verification:
            progress_writer.emit(
                "verification_result",
                {
                    "command": item.command,
                    "exit_code": item.exit_code,
                },
            )

    status = determine_status(
        kimi_exit_code=int(kimi_result["exit_code"]),
        changed_files=changed_files,
        verification=verification,
    )

    final_message = first_non_empty(
        str(kimi_result.get("final_message", "")).strip(),
        str(kimi_result["stdout"]).strip(),
        str(kimi_result["stderr"]).strip(),
    )
    if not final_message:
        final_message = "Kimi did not return a message."

    progress_writer.emit(
        "final_message",
        {
            "text": final_message,
        },
    )

    progress_writer.emit(
        "completed",
        {
            "status": status,
            "kimi_exit_code": int(kimi_result["exit_code"]),
            "changed_files": changed_files,
        },
    )

    return {
        "status": status,
        "kimi_exit_code": int(kimi_result["exit_code"]),
        "retryable": status == "retryable_error",
        "task": args.task,
        "cwd": str(cwd),
        "target_files": [str(path) for path in target_paths],
        "context_files": [str(path) for path in context_paths],
        "reference_images": [str(path) for path in reference_image_paths],
        "changed_files": changed_files,
        "unchanged_target_files": unchanged_target_files,
        "file_results": file_results,
        "verification": [item.to_dict() for item in verification],
        "final_message": final_message,
    }


def failure_payload(
    message: str,
    cwd: Path,
    task: str,
    kimi_exit_code: int = 1,
) -> dict[str, object]:
    return {
        "status": "failed",
        "kimi_exit_code": kimi_exit_code,
        "retryable": False,
        "task": task,
        "cwd": str(cwd),
        "target_files": [],
        "context_files": [],
        "reference_images": [],
        "changed_files": [],
        "unchanged_target_files": [],
        "file_results": [],
        "verification": [],
        "final_message": message,
    }


class ProgressWriter:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._lock = threading.Lock()
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event_type: str, payload: dict[str, object]) -> None:
        if self.path is None:
            return
        event = ProgressEvent(
            type=event_type,
            timestamp=time.time(),
            payload=payload,
        )
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(event.to_json_line())
                handle.write("\n")


def resolve_progress_path(raw_path: str, cwd: Path) -> Path | None:
    if not raw_path:
        return None
    return resolve_path(raw_path, cwd)


def emit_file_events(
    file_results: Sequence[dict[str, str]],
    progress_writer: ProgressWriter,
) -> None:
    for item in file_results:
        status = item["status"]
        path = item["path"]
        if status == "created":
            progress_writer.emit("file_created", {"path": path})
        elif status == "modified":
            progress_writer.emit("file_modified", {"path": path})


def dedupe_paths(
    raw_paths: Sequence[str],
    cwd: Path,
    allow_missing: bool,
    *,
    enforce_within_cwd: bool = True,
    missing_label: str = "Context file",
) -> list[Path]:
    resolved: list[Path] = []
    seen: set[Path] = set()
    for raw in raw_paths:
        path = resolve_path(raw, cwd)
        if path in seen:
            continue
        if enforce_within_cwd:
            ensure_within_cwd(path, cwd)
        if not allow_missing and not path.exists():
            raise FileNotFoundError(f"{missing_label} does not exist: {path}")
        seen.add(path)
        resolved.append(path)
    return resolved


def resolve_path(raw: str, cwd: Path) -> Path:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = cwd / candidate
    return candidate.resolve()


def ensure_within_cwd(path: Path, cwd: Path) -> None:
    try:
        path.relative_to(cwd)
    except ValueError as exc:
        raise ValueError(f"Path must stay within --cwd: {path}") from exc


def snapshot_file(path: Path) -> FileSnapshot:
    if not path.exists():
        return FileSnapshot(path=path, existed=False, digest=None)
    data = path.read_bytes()
    return FileSnapshot(path=path, existed=True, digest=hashlib.sha256(data).hexdigest())


def collect_file_results(
    target_paths: Sequence[Path],
    before: dict[Path, FileSnapshot],
) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for path in target_paths:
        current = snapshot_file(path)
        previous = before[path]
        if not previous.existed and current.existed:
            status = "created"
        elif not previous.existed and not current.existed:
            status = "missing_before"
        elif previous.existed and not current.existed:
            status = "modified"
        elif previous.digest != current.digest:
            status = "modified"
        else:
            status = "unchanged"
        results.append({"path": str(path), "status": status})
    return results


def detect_repo_facts(cwd: Path) -> list[str]:
    facts: list[str] = []
    package_json = cwd / "package.json"
    if package_json.exists():
        facts.append("package.json present")
        package_name = read_package_name(package_json)
        if package_name:
            facts.append(f"package name: {package_name}")

    lock_markers = {
        "pnpm-lock.yaml": "package manager: pnpm",
        "package-lock.json": "package manager: npm",
        "yarn.lock": "package manager: yarn",
        "bun.lockb": "package manager: bun",
        "bun.lock": "package manager: bun",
    }
    for filename, description in lock_markers.items():
        if (cwd / filename).exists():
            facts.append(description)

    framework_markers = {
        "next.config.js": "framework hint: Next.js",
        "next.config.ts": "framework hint: Next.js",
        "next.config.mjs": "framework hint: Next.js",
        "vite.config.ts": "framework hint: Vite",
        "vite.config.js": "framework hint: Vite",
        "vite.config.mjs": "framework hint: Vite",
        "tailwind.config.js": "styling hint: Tailwind CSS",
        "tailwind.config.ts": "styling hint: Tailwind CSS",
        "tailwind.config.cjs": "styling hint: Tailwind CSS",
        "postcss.config.js": "styling hint: PostCSS",
        "postcss.config.cjs": "styling hint: PostCSS",
    }
    for filename, description in framework_markers.items():
        if (cwd / filename).exists():
            facts.append(description)

    for directory in ("src", "app", "components", "pages", "styles"):
        if (cwd / directory).is_dir():
            facts.append(f"directory present: {directory}/")

    if not facts:
        facts.append("No common frontend repo markers detected in --cwd.")
    return facts


def read_package_name(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    name = payload.get("name")
    return str(name) if isinstance(name, str) else ""


def build_prompt(
    *,
    task: str,
    cwd: Path,
    target_paths: Sequence[Path],
    context_paths: Sequence[Path],
    reference_image_paths: Sequence[Path] = (),
    constraints: Sequence[str],
    repo_facts: Sequence[str],
) -> str:
    success_criteria = [
        "Complete the requested frontend or UI change inside the listed editable files.",
        "Keep implementation style, dependencies, and architecture aligned with the existing codebase.",
        "Preserve responsive behavior and accessibility unless the task explicitly changes them.",
        "Leave a concise final report using the required response format.",
    ]
    base_constraints = [
        "Stay consistent with the current framework, styling stack, and design language.",
        "Prefer the smallest complete change that satisfies the task.",
    ]
    all_constraints = [*base_constraints, *constraints]
    editable_intro = format_path_list(target_paths, cwd)
    readonly_intro = format_path_list(context_paths, cwd) if context_paths else "- None"
    reference_intro = (
        format_path_list(reference_image_paths, cwd) if reference_image_paths else "- None"
    )
    target_blocks = render_file_blocks(target_paths, cwd, allow_missing=True)
    context_blocks = render_file_blocks(context_paths, cwd, allow_missing=False) or "No context files were provided."

    sections = [
        ("Role", "You are Kimi acting as a frontend and UI specialist inside an existing local repository."),
        ("Task", task.strip()),
        (
            "Reference Images",
            "\n".join(
                [
                    "These local image files are part of the task input:",
                    reference_intro,
                    "",
                    "Inspect these image files directly before editing.",
                    "Use local file or media-reading tools if needed.",
                    "Treat the image files themselves as the visual source of truth instead of relying on rewritten textual substitutes.",
                ]
            ),
        ),
        ("Success Criteria", bullet_block(success_criteria)),
        (
            "Editable Files",
            "\n".join(
                [
                    "Only the following files may be edited:",
                    editable_intro,
                    "",
                    "Current editable file contents:",
                    target_blocks,
                ]
            ),
        ),
        (
            "Read-only Context",
            "\n".join(
                [
                    "These files are reference-only and must not be edited:",
                    readonly_intro,
                    "",
                    "Current context file contents:",
                    context_blocks,
                ]
            ),
        ),
        ("Repo Facts", bullet_block(repo_facts)),
        ("Constraints", bullet_block(all_constraints)),
        (
            "Execution Rules",
            bullet_block(
                [
                    "Read the editable files and read-only context before making changes.",
                    "Only modify the listed editable files.",
                    "Do not create files outside the editable file list.",
                    "If an editable file does not exist yet, you may create it because it is explicitly listed.",
                    "Keep the implementation within the existing project stack and patterns.",
                    "Aim for the smallest complete change that can be validated.",
                ]
            ),
        ),
        (
            "Final Response Format",
            "\n".join(
                [
                    "Reply using exactly these headings and no others:",
                    "Outcome:",
                    "Summary:",
                    "Validation:",
                    "Open Risks:",
                ]
            ),
        ),
    ]

    lines = [f"Working directory: {cwd}"]
    for title, body in sections:
        lines.append("")
        lines.append(title)
        lines.append(body)
    return "\n".join(lines).strip() + "\n"


def bullet_block(items: Sequence[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def format_path_list(paths: Sequence[Path], cwd: Path) -> str:
    return "\n".join(f"- {display_path(path, cwd)}" for path in paths)


def render_file_blocks(paths: Sequence[Path], cwd: Path, allow_missing: bool) -> str:
    blocks = [render_file_block(path, cwd, allow_missing=allow_missing) for path in paths]
    return "\n\n".join(blocks)


def render_file_block(path: Path, cwd: Path, allow_missing: bool) -> str:
    header = f"### {display_path(path, cwd)}"
    if not path.exists():
        if not allow_missing:
            raise FileNotFoundError(f"Context file does not exist: {path}")
        return "\n".join([header, "(File does not exist yet. You may create it because it is editable.)"])

    content = path.read_text(encoding="utf-8", errors="replace")
    truncated = False
    if len(content) > MAX_FILE_CHARS:
        content = content[:MAX_FILE_CHARS]
        truncated = True
    fence = "\n".join([header, "```text", content, "```"])
    if truncated:
        fence += f"\n(Truncated to {MAX_FILE_CHARS} characters.)"
    return fence


def display_path(path: Path, cwd: Path) -> str:
    try:
        return str(path.relative_to(cwd))
    except ValueError:
        return str(path)


def build_kimi_command(
    *,
    cwd: Path,
    model: str,
    thinking: bool | None,
    max_steps_per_turn: int | None,
) -> list[str]:
    command = ["kimi", "--print", "--output-format", "stream-json", "-w", str(cwd)]
    if model:
        command.extend(["-m", model])
    if thinking is True:
        command.append("--thinking")
    elif thinking is False:
        command.append("--no-thinking")
    if max_steps_per_turn is not None:
        command.extend(["--max-steps-per-turn", str(max_steps_per_turn)])
    return command


def run_kimi_with_retry(
    *,
    prompt: str,
    cwd: Path,
    model: str,
    thinking: bool | None,
    max_steps_per_turn: int | None,
    progress_writer: ProgressWriter,
) -> dict[str, object]:
    command = build_kimi_command(
        cwd=cwd,
        model=model,
        thinking=thinking,
        max_steps_per_turn=max_steps_per_turn,
    )
    progress_writer.emit("kimi_started", {"command": command})
    first = run_streaming_subprocess(
        command,
        cwd=cwd,
        input_text=prompt,
        progress_writer=progress_writer,
    )
    if first["exit_code"] != RETRYABLE_EXIT_CODE:
        return first
    progress_writer.emit("retry", {"reason": "exit_code_75", "attempt": 2})
    second = run_streaming_subprocess(
        command,
        cwd=cwd,
        input_text=prompt,
        progress_writer=progress_writer,
    )
    return second


def run_streaming_subprocess(
    command: Sequence[str],
    *,
    cwd: Path,
    input_text: str | None = None,
    progress_writer: ProgressWriter,
) -> dict[str, object]:
    process = subprocess.Popen(
        list(command),
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    assert process.stdin is not None

    stdout_lines: list[str] = []
    stderr_chunks: list[str] = []
    messages: list[dict[str, object]] = []

    def read_stdout() -> None:
        for line in process.stdout:
            stdout_lines.append(line)
            parsed = parse_stream_json_line(line)
            if parsed is not None:
                messages.append(parsed)
                emit_stream_message_event(parsed, progress_writer)

    def read_stderr() -> None:
        for line in process.stderr:
            stderr_chunks.append(line)

    stdout_thread = threading.Thread(target=read_stdout, daemon=True)
    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    try:
        if input_text:
            process.stdin.write(input_text)
        process.stdin.close()
    except BrokenPipeError:
        pass

    exit_code = process.wait()
    stdout_thread.join()
    stderr_thread.join()

    stdout_text = "".join(stdout_lines)
    stderr_text = "".join(stderr_chunks)
    final_message = extract_final_message_from_messages(messages)
    return {
        "exit_code": exit_code,
        "stdout": tail_text(stdout_text),
        "stderr": tail_text(stderr_text),
        "final_message": final_message,
    }


def parse_stream_json_line(line: str) -> dict[str, object] | None:
    stripped = line.strip()
    if not stripped:
        return None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def extract_final_message_from_messages(messages: Sequence[dict[str, object]]) -> str:
    assistant_messages = [
        extract_message_content(message)
        for message in messages
        if message.get("role") == "assistant"
    ]
    assistant_messages = [message for message in assistant_messages if message.strip()]
    if assistant_messages:
        return assistant_messages[-1]
    return ""


def extract_message_content(message: dict[str, object]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text", "")
                if isinstance(text, str):
                    chunks.append(text)
        return "".join(chunks)
    return ""


def emit_stream_message_event(
    message: dict[str, object],
    progress_writer: ProgressWriter,
) -> None:
    role = message.get("role")
    if role != "assistant":
        return
    content = extract_message_content(message).strip()
    if not content:
        return
    progress_writer.emit(
        "kimi_message",
        {
            "role": str(role),
            "text": tail_text(content, 600),
        },
    )


def run_verification_commands(commands: Sequence[str], cwd: Path) -> list[VerificationResult]:
    results: list[VerificationResult] = []
    for command in commands:
        process = subprocess.run(
            command,
            cwd=cwd,
            shell=True,
            text=True,
            capture_output=True,
        )
        results.append(
            VerificationResult(
                command=command,
                exit_code=process.returncode,
                stdout_tail=tail_text(process.stdout),
                stderr_tail=tail_text(process.stderr),
            )
        )
    return results


def determine_status(
    *,
    kimi_exit_code: int,
    changed_files: Sequence[str],
    verification: Sequence[VerificationResult],
) -> str:
    if kimi_exit_code == RETRYABLE_EXIT_CODE:
        return "retryable_error"
    if kimi_exit_code != 0:
        return "failed"
    if not changed_files:
        return "no_change"
    if any(result.exit_code != 0 for result in verification):
        return "partial"
    return "success"


def render_text_summary(payload: dict[str, object]) -> str:
    verification = payload.get("verification", [])
    lines = [
        f"status: {payload.get('status', '')}",
        f"kimi_exit_code: {payload.get('kimi_exit_code', '')}",
    ]

    changed_files = payload.get("changed_files", [])
    if changed_files:
        lines.append("changed_files:")
        lines.extend(f"- {path}" for path in changed_files)
    else:
        lines.append("changed_files: none")

    reference_images = payload.get("reference_images", [])
    if reference_images:
        lines.append("reference_images:")
        lines.extend(f"- {path}" for path in reference_images)
    else:
        lines.append("reference_images: none")

    if verification:
        lines.append("verification:")
        for item in verification:
            if isinstance(item, dict):
                command = item.get("command", "")
                exit_code = item.get("exit_code", "")
                lines.append(f"- {command} -> {exit_code}")
    else:
        lines.append("verification: none")

    lines.append("")
    lines.append("final_message:")
    lines.append(str(payload.get("final_message", "")).strip())
    return "\n".join(lines).strip()


def tail_text(text: str, limit: int = TAIL_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def first_non_empty(*values: str) -> str:
    for value in values:
        if value:
            return value
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
