# kimi-code-plugin-codex

This repository hosts a local Codex plugin that routes bounded frontend and UI tasks through the `kimi` CLI and returns structured results to Codex.

## What is in this repo

- a repo-local Codex plugin at `plugins/kimi-ui-workflow/`
- a skill that defines when the workflow should be used
- a Python adapter that builds the prompt, invokes `kimi`, tracks target-file changes, and runs optional verification commands
- pytest coverage for prompt assembly, change tracking, and result mapping

## Repository Layout

```text
plugins/kimi-ui-workflow/
├── .codex-plugin/plugin.json
├── README.md
├── scripts/run_kimi_ui_task.py
├── skills/kimi-ui-task/SKILL.md
└── tests/test_run_kimi_ui_task.py
```

## How it works

1. Codex identifies a frontend or UI task with explicit editable files.
2. The `kimi-ui-task` skill calls the adapter script.
3. The adapter collects:
   - the task description
   - editable target files
   - optional read-only context files
   - optional constraints
   - repo facts inferred from the working directory
4. The adapter sends a fixed prompt to `kimi --quiet`.
5. After Kimi returns, the adapter:
   - compares target files before and after the run
   - optionally runs verification commands
   - emits either a text summary or stable JSON

## Quick Start

```bash
python3 plugins/kimi-ui-workflow/scripts/run_kimi_ui_task.py \
  --cwd /path/to/repo \
  --task "Tighten the hero layout and improve mobile spacing" \
  --target-file src/App.tsx \
  --target-file src/components/Hero.tsx \
  --context-file src/styles.css \
  --constraint "Keep the existing color palette and typography" \
  --verify-cmd "pnpm lint" \
  --json
```

## Development

Prerequisites:

- `python3`
- local `kimi` CLI available on `PATH`
- `pytest` installed for the Python environment you use to run tests

Run tests:

```bash
pytest plugins/kimi-ui-workflow/tests -q
```

The plugin-specific workflow and adapter details live in `plugins/kimi-ui-workflow/README.md`.

## License

This repository is licensed under the MIT License. See `LICENSE`.
