---
name: kimi-ui-task
description: Use when a frontend or UI task should be executed by the local kimi CLI with explicit editable files, optional screenshots or mockups from the current Codex thread, optional read-only context, and structured JSON results.
---

# Kimi UI Task

Use this skill when the user wants Kimi to perform a bounded frontend or UI change inside a local codebase.

## When to use it

- the task is mainly frontend, styling, layout, interaction, or UI polish
- the editable files are known up front
- Codex should hand execution to `kimi` but still keep a structured result

Do not use this skill until you know the editable files. If they are unclear, inspect the repo first and narrow the file list before invoking the adapter.

## Inputs

- `--task`: required; the concrete UI or frontend job
- `--target-file`: required and repeatable; the only files Kimi is allowed to edit
- `--context-file`: optional and repeatable; read-only supporting files
- `--constraint`: optional and repeatable; product, branding, stack, or quality constraints
- `--reference-image`: optional and repeatable; local image file path that Kimi should inspect directly
- `--verify-cmd`: optional and repeatable; post-edit verification commands
- `--cwd`: optional; target repo root or working directory
- `--model`: optional; Kimi model override
- `--thinking` / `--no-thinking`: optional; pass through Kimi thinking mode
- `--max-steps-per-turn`: optional; pass through Kimi turn budget
- `--progress-file`: optional; write JSONL progress events to a file while the adapter runs
- `--json`: optional; emit machine-readable output

## Image Inputs

- If the user attached a screenshot, mockup, or reference image in the current Codex thread, inspect it before finalizing the edit scope.
- External scripts and CLIs do not automatically receive thread images as file paths. If a downstream tool needs a file, export the image from thread history first.
- Use `scripts/export_thread_image.py` to export the first or latest thread image to a temp file or explicit destination.
- Pass exported images to `run_kimi_ui_task.py` with `--reference-image` so the adapter can hand Kimi a real local image path.
- If the user wants to generate or edit the bitmap asset itself rather than update code, use `imagegen` instead of this skill.

## Workflow

1. Confirm the task is frontend/UI focused.
2. Identify the exact editable files.
3. If the user supplied screenshots or mockups and a file path is useful, export the relevant thread image first:

```bash
python3 /absolute/path/to/kimi-code-ui/scripts/export_thread_image.py --json
```

4. Collect any read-only context files and constraints that Kimi needs. Keep screenshots and mockups as image files; do not rewrite them into substitute textual constraints.
5. Run the adapter from the installed plugin location. Resolve the script path relative to this skill file or the plugin root; do not assume the current working directory is the plugin repository.

```bash
python3 /absolute/path/to/kimi-code-ui/scripts/run_kimi_ui_task.py \
  --cwd /path/to/repo \
  --task "Refine the dashboard table layout for mobile" \
  --target-file src/pages/dashboard.tsx \
  --target-file src/components/DataTable.tsx \
  --reference-image /tmp/codex-thread-image-thread-1.png \
  --context-file src/styles/tokens.css \
  --constraint "Keep the existing visual language" \
  --progress-file output/kimi-progress.jsonl \
  --verify-cmd "pnpm lint" \
  --json
```

In this plugin layout, the adapter script lives at `scripts/run_kimi_ui_task.py` under the plugin root.
The thread-image export helper lives at `scripts/export_thread_image.py` under the plugin root.

6. Read the adapter result rather than relying on raw `kimi` output.
7. If `status` is `partial`, `retryable_error`, or `failed`, stop immediately.
8. Report the adapter result and `final_message` back to the user.
9. Do not manually implement a fallback solution after an adapter failure.

## Progress Events

If `--progress-file` is provided, the adapter appends JSONL events while it runs. Typical events include:

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

## Output Contract

With `--json`, the adapter returns:

- `status`
- `kimi_exit_code`
- `retryable`
- `task`
- `cwd`
- `target_files`
- `context_files`
- `reference_images`
- `changed_files`
- `unchanged_target_files`
- `file_results`
- `verification`
- `final_message`

## Guardrails

- Only use files listed with `--target-file` as editable scope.
- Treat `--context-file` as read-only context.
- Do not assume a thread image is already available as a filesystem path; export it first if a tool requires one.
- v1 does not discover unexpected file edits outside `--target-file`.
- v1 starts a fresh Kimi session on every run.
- If the adapter returns `partial`, `retryable_error`, or `failed`, do not continue by implementing the task yourself.
