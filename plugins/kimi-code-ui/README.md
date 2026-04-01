# Kimi Code UI Plugin

This plugin adds a single Codex skill that routes bounded frontend and UI work through the local `kimi` CLI.

## What it does

- accepts a task plus an explicit list of editable files
- reads optional context files and repo facts
- can pass local screenshot or mockup file paths through to Kimi
- builds a stable prompt for `kimi` and consumes structured `stream-json` output
- tracks changes only for the declared editable files
- can append structured JSONL progress events to an optional progress file
- optionally runs verification commands
- returns either human-readable text or a stable JSON payload

## Layout

- `.codex-plugin/plugin.json`: plugin manifest
- `skills/kimi-ui-task/SKILL.md`: skill instructions
- `scripts/export_thread_image.py`: export the latest or first thread image from Codex app-server history
- `scripts/run_kimi_ui_task.py`: adapter between Codex and `kimi`
- `tests/test_run_kimi_ui_task.py`: pytest coverage for prompt assembly and result mapping

## Quick Start

The example below assumes your current directory is this plugin root. If Codex invokes the skill for you, it should resolve the installed plugin path automatically.

```bash
python3 scripts/run_kimi_ui_task.py \
  --cwd /path/to/repo \
  --task "Tighten the hero layout and improve mobile spacing" \
  --target-file src/App.tsx \
  --target-file src/components/Hero.tsx \
  --reference-image /tmp/mockup.png \
  --context-file src/styles.css \
  --constraint "Keep the existing color palette and typography" \
  --progress-file output/kimi-progress.jsonl \
  --verify-cmd "pnpm lint" \
  --json
```

## Progress File

When `--progress-file` is set, the adapter appends JSONL events during execution. That file is intended for polling or log-tail style observation without changing the final stdout contract.

Typical events:

- `run_started`
- `repo_facts_detected`
- `kimi_started`
- `kimi_message`
- `file_created`
- `file_modified`
- `verification_started`
- `verification_result`
- `retry`
- `final_message`
- `completed`

## Notes

- v1 starts a fresh `kimi` session on every run.
- v1 only tracks files listed with `--target-file`.
- Thread images still need to be exported to a real file before they can be passed to the adapter.
- The adapter passes reference image file paths to Kimi in the task prompt so Kimi can inspect the local files directly.
- v1 still does not support persisted multi-turn sessions.
- If the adapter reports `partial`, `retryable_error`, or `failed`, Codex should stop and report that result instead of falling back to a manual implementation.
