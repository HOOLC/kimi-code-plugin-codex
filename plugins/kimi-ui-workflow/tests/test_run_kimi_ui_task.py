from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "run_kimi_ui_task.py"
)
SPEC = importlib.util.spec_from_file_location("run_kimi_ui_task", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_build_prompt_contains_sections_and_truncation(tmp_path: Path) -> None:
    cwd = tmp_path
    target = cwd / "src" / "App.tsx"
    target.parent.mkdir(parents=True)
    target.write_text("A" * (module.MAX_FILE_CHARS + 10), encoding="utf-8")
    context = cwd / "src" / "styles.css"
    context.write_text("body { color: black; }", encoding="utf-8")

    prompt = module.build_prompt(
        task="Tighten spacing in the hero",
        cwd=cwd,
        target_paths=[target],
        context_paths=[context],
        constraints=["Keep existing tokens"],
        repo_facts=["package.json present"],
    )

    assert "Role" in prompt
    assert "Task" in prompt
    assert "Success Criteria" in prompt
    assert "Editable Files" in prompt
    assert "Read-only Context" in prompt
    assert "Repo Facts" in prompt
    assert "Constraints" in prompt
    assert "Execution Rules" in prompt
    assert "Final Response Format" in prompt
    assert "src/App.tsx" in prompt
    assert "(Truncated to " in prompt
    assert "Keep existing tokens" in prompt


def test_collect_file_results_tracks_modified_created_unchanged_missing(tmp_path: Path) -> None:
    unchanged = tmp_path / "unchanged.tsx"
    modified = tmp_path / "modified.tsx"
    created = tmp_path / "created.tsx"
    missing = tmp_path / "missing.tsx"

    unchanged.write_text("same", encoding="utf-8")
    modified.write_text("before", encoding="utf-8")

    paths = [unchanged, modified, created, missing]
    before = {path: module.snapshot_file(path) for path in paths}

    modified.write_text("after", encoding="utf-8")
    created.write_text("new", encoding="utf-8")

    results = module.collect_file_results(paths, before)
    by_path = {item["path"]: item["status"] for item in results}

    assert by_path[str(unchanged)] == "unchanged"
    assert by_path[str(modified)] == "modified"
    assert by_path[str(created)] == "created"
    assert by_path[str(missing)] == "missing_before"


def test_determine_status_maps_exit_codes_and_verification() -> None:
    ok = module.VerificationResult("pnpm lint", 0, "", "")
    bad = module.VerificationResult("pnpm test", 1, "", "boom")

    assert module.determine_status(kimi_exit_code=0, changed_files=[], verification=[]) == "no_change"
    assert module.determine_status(kimi_exit_code=0, changed_files=["a"], verification=[]) == "success"
    assert module.determine_status(kimi_exit_code=0, changed_files=["a"], verification=[ok, bad]) == "partial"
    assert module.determine_status(kimi_exit_code=75, changed_files=["a"], verification=[]) == "retryable_error"
    assert module.determine_status(kimi_exit_code=1, changed_files=["a"], verification=[]) == "failed"


def test_build_kimi_command_uses_print_stream_json(tmp_path: Path) -> None:
    command = module.build_kimi_command(
        cwd=tmp_path,
        model="kimi-test",
        thinking=False,
        max_steps_per_turn=12,
    )

    assert command[:4] == ["kimi", "--print", "--output-format", "stream-json"]
    assert "-w" in command
    assert "--quiet" not in command
    assert command[-5:] == ["-m", "kimi-test", "--no-thinking", "--max-steps-per-turn", "12"]


def test_extract_final_message_from_stream_messages_uses_last_assistant_message() -> None:
    messages = [
        {"role": "assistant", "content": "Let me inspect the files."},
        {"role": "tool", "content": "file output"},
        {"role": "assistant", "content": [{"type": "text", "text": "Outcome: Success"}]},
    ]

    assert module.extract_final_message_from_messages(messages) == "Outcome: Success"


def test_progress_writer_and_file_events(tmp_path: Path) -> None:
    progress_path = tmp_path / "progress.jsonl"
    writer = module.ProgressWriter(progress_path)

    writer.emit("run_started", {"task": "demo"})
    module.emit_file_events(
        [
            {"path": str(tmp_path / "index.html"), "status": "created"},
            {"path": str(tmp_path / "styles.css"), "status": "modified"},
            {"path": str(tmp_path / "app.js"), "status": "unchanged"},
        ],
        writer,
    )

    lines = progress_path.read_text(encoding="utf-8").strip().splitlines()
    events = [module.json.loads(line) for line in lines]

    assert events[0]["type"] == "run_started"
    assert events[1]["type"] == "file_created"
    assert events[2]["type"] == "file_modified"
    assert len(events) == 3


def test_emit_stream_message_event_writes_assistant_text(tmp_path: Path) -> None:
    progress_path = tmp_path / "progress.jsonl"
    writer = module.ProgressWriter(progress_path)

    module.emit_stream_message_event(
        {"role": "assistant", "content": [{"type": "text", "text": "Planning changes"}]},
        writer,
    )

    events = [
        module.json.loads(line)
        for line in progress_path.read_text(encoding="utf-8").strip().splitlines()
    ]
    assert events[0]["type"] == "kimi_message"
    assert events[0]["text"] == "Planning changes"


def test_execute_success_runs_verification_and_tracks_changes(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "src" / "App.tsx"
    target.parent.mkdir(parents=True)
    target.write_text("before", encoding="utf-8")
    context = tmp_path / "src" / "tokens.css"
    context.write_text(":root {}", encoding="utf-8")

    monkeypatch.setattr(module, "which", lambda _: "/usr/bin/kimi")

    def fake_run_kimi_with_retry(**kwargs):
        target.write_text("after", encoding="utf-8")
        return {"exit_code": 0, "stdout": "Outcome:\nDone", "stderr": ""}

    def fake_run_verification_commands(commands, cwd):
        assert commands == ["pnpm lint"]
        assert cwd == tmp_path
        return [module.VerificationResult("pnpm lint", 0, "ok", "")]

    monkeypatch.setattr(module, "run_kimi_with_retry", fake_run_kimi_with_retry)
    monkeypatch.setattr(module, "run_verification_commands", fake_run_verification_commands)

    progress_path = tmp_path / "progress.jsonl"
    args = argparse.Namespace(
        task="Improve the header spacing",
        target_files=["src/App.tsx"],
        context_files=["src/tokens.css"],
        constraint=["Keep existing spacing scale"],
        verify_cmd=["pnpm lint"],
        cwd=str(tmp_path),
        model="",
        thinking=None,
        max_steps_per_turn=None,
        progress_file=str(progress_path),
        json=True,
    )

    payload = module.execute(args)

    assert payload["status"] == "success"
    assert payload["changed_files"] == [str(target)]
    assert payload["verification"][0]["exit_code"] == 0
    assert "Outcome:" in payload["final_message"]
    progress_events = [
        module.json.loads(line)
        for line in progress_path.read_text(encoding="utf-8").strip().splitlines()
    ]
    assert progress_events[0]["type"] == "run_started"
    assert progress_events[-2]["type"] == "final_message"
    assert "Outcome:" in progress_events[-2]["text"]
    assert progress_events[-1]["type"] == "completed"


def test_execute_returns_no_change_without_verification(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "src" / "App.tsx"
    target.parent.mkdir(parents=True)
    target.write_text("before", encoding="utf-8")

    monkeypatch.setattr(module, "which", lambda _: "/usr/bin/kimi")
    monkeypatch.setattr(
        module,
        "run_kimi_with_retry",
        lambda **kwargs: {"exit_code": 0, "stdout": "Outcome:\nNo changes", "stderr": ""},
    )

    called = {"verify": False}

    def fake_verify(commands, cwd):
        called["verify"] = True
        return []

    monkeypatch.setattr(module, "run_verification_commands", fake_verify)

    args = argparse.Namespace(
        task="Review the file",
        target_files=["src/App.tsx"],
        context_files=[],
        constraint=[],
        verify_cmd=["pnpm lint"],
        cwd=str(tmp_path),
        model="",
        thinking=None,
        max_steps_per_turn=None,
        progress_file="",
        json=True,
    )

    payload = module.execute(args)

    assert payload["status"] == "no_change"
    assert payload["changed_files"] == []
    assert called["verify"] is False


def test_execute_maps_retryable_and_failed_exit_codes(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "src" / "App.tsx"
    target.parent.mkdir(parents=True)
    target.write_text("before", encoding="utf-8")

    monkeypatch.setattr(module, "which", lambda _: "/usr/bin/kimi")

    args = argparse.Namespace(
        task="Change button padding",
        target_files=["src/App.tsx"],
        context_files=[],
        constraint=[],
        verify_cmd=[],
        cwd=str(tmp_path),
        model="",
        thinking=None,
        max_steps_per_turn=None,
        progress_file="",
        json=True,
    )

    monkeypatch.setattr(
        module,
        "run_kimi_with_retry",
        lambda **kwargs: {"exit_code": 75, "stdout": "", "stderr": "rate limited"},
    )
    payload = module.execute(args)
    assert payload["status"] == "retryable_error"
    assert payload["retryable"] is True

    monkeypatch.setattr(
        module,
        "run_kimi_with_retry",
        lambda **kwargs: {"exit_code": 1, "stdout": "", "stderr": "auth failed"},
    )
    payload = module.execute(args)
    assert payload["status"] == "failed"
    assert payload["final_message"] == "auth failed"


def test_context_file_must_exist(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "src" / "App.tsx"
    target.parent.mkdir(parents=True)
    target.write_text("before", encoding="utf-8")

    monkeypatch.setattr(module, "which", lambda _: "/usr/bin/kimi")

    args = argparse.Namespace(
        task="Change button padding",
        target_files=["src/App.tsx"],
        context_files=["src/missing.css"],
        constraint=[],
        verify_cmd=[],
        cwd=str(tmp_path),
        model="",
        thinking=None,
        max_steps_per_turn=None,
        progress_file="",
        json=True,
    )

    try:
        module.execute(args)
    except FileNotFoundError as exc:
        assert "Context file does not exist" in str(exc)
    else:  # pragma: no cover - explicit failure branch
        raise AssertionError("expected FileNotFoundError")
