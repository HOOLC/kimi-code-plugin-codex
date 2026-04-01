# kimi-code-plugin-codex

Use this repository when you want Codex to hand off bounded frontend and UI work to the local `kimi` CLI while keeping the edit scope explicit and the result auditable.

## What You Get

- a Codex plugin at `plugins/kimi-code-ui/`
- a `kimi-ui-task` skill for bounded frontend and UI work
- bounded execution through the local `kimi` CLI with explicit editable files
- structured output that Codex can inspect instead of relying on raw CLI text

## Requirements

- `python3`
- local `kimi` CLI available on `PATH`
- Codex using `~/.codex` or another `CODEX_HOME`

## Install In Codex

Choose one installation mode depending on how you want the integration to appear in Codex.

### Option 1: Install As A Codex Plugin

Use this if you want the full plugin entry in Codex.

1. Clone this repository anywhere on your machine.
2. Copy the plugin bundle into the Codex plugin cache:

```bash
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
REPO_DIR="/path/to/kimi-code-plugin-codex"

mkdir -p "$CODEX_HOME/plugins/cache/kimi-code-plugin-codex/kimi-code-ui/local"
rsync -a --delete \
  "$REPO_DIR/plugins/kimi-code-ui/" \
  "$CODEX_HOME/plugins/cache/kimi-code-plugin-codex/kimi-code-ui/local/"
```

3. Enable the plugin in `$CODEX_HOME/config.toml`:

```toml
[plugins."kimi-code-ui@kimi-code-plugin-codex"]
enabled = true
```

4. Restart Codex.

Notes:

- If you previously enabled `kimi-ui-workflow@kimi-code-plugin-codex`, replace it with `kimi-code-ui@kimi-code-plugin-codex`.
- This mode installs the plugin manifest, assets, script, and bundled skill together.

### Option 2: Reference Only The Skill

Use this if you only want the `kimi-ui-task` skill and do not need the plugin entry or metadata in Codex.

1. Clone this repository anywhere on your machine and keep it there.
2. Link the skill directory into Codex:

```bash
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
REPO_DIR="/path/to/kimi-code-plugin-codex"

mkdir -p "$CODEX_HOME/skills"
ln -sfn \
  "$REPO_DIR/plugins/kimi-code-ui/skills/kimi-ui-task" \
  "$CODEX_HOME/skills/kimi-ui-task"
```

3. Restart Codex.

Notes:

- This mode exposes only the `kimi-ui-task` skill.
- Use a symlink rather than copying the skill so the skill continues to point at the adapter that lives in this repository.

## Use It

After installation, ask Codex to use `kimi-ui-task` for a frontend or UI task where the editable files are known up front.

Typical fit:

- layout or spacing fixes
- component-level styling work
- bounded UI polish inside a known file list
- tasks where you want optional `lint` or `test` verification after the edit

## How It Works

1. Codex identifies a frontend or UI task with explicit editable files.
2. The `kimi-ui-task` skill calls the adapter script.
3. The adapter collects the task, editable files, optional read-only context, optional constraints, and repo facts from `--cwd`.
4. The adapter sends a fixed prompt to `kimi` and consumes structured `stream-json` output.
5. After Kimi returns, the adapter reports changed files, verification results, and a stable final status.

## License

This repository is licensed under the MIT License. See `LICENSE`.
