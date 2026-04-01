# Contributing

## Development Setup

1. Make sure `python3` is available.
2. Make sure the local `kimi` CLI is installed and available on `PATH`.
3. Install `pytest` in the Python environment you plan to use for local checks.

## Making Changes

- Keep the plugin repo-local unless a change explicitly introduces marketplace support.
- Preserve the adapter's bounded-edit model: only declared `--target-file` paths are treated as editable.
- Prefer small changes that keep prompt structure and JSON output backward compatible.
- Update tests when changing prompt assembly, status mapping, or file tracking behavior.

## Verification

Run:

```bash
python3 -m pytest plugins/kimi-code-ui/tests -q
```

If you change the adapter CLI or output contract, update:

- `README.md`
- `plugins/kimi-code-ui/README.md`
- `plugins/kimi-code-ui/skills/kimi-ui-task/SKILL.md`
