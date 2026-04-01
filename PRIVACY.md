# Privacy Policy

Last updated: 2026-04-01

## Summary

`kimi-code-plugin-codex` is a local Codex plugin repository. The plugin runs commands on the local machine and can send task prompts and file context to the locally installed `kimi` CLI when the workflow is invoked.

## What data may be processed

When you run the plugin, the following data may be processed:

- the task description you provide
- paths and contents of files explicitly passed as editable or read-only context
- repository facts inferred from the current working directory
- optional verification command output
- optional progress events written to a local JSONL file

## How data is used

This data is used only to:

- assemble a bounded prompt for `kimi`
- execute the requested frontend or UI task
- report progress and final status back to Codex
- optionally run local verification commands

## Data sharing

The plugin itself does not operate a hosted backend. However, when `kimi` is invoked, the prompt and any included file context may be sent to the upstream Kimi service according to that service's own policies and configuration.

## Local storage

The plugin may create or update local files in the target working directory, including:

- user-requested editable files
- optional progress JSONL files
- other files explicitly allowed by the workflow inputs

## Contact

For questions about this repository, use the GitHub repository:

- [https://github.com/HOOLC/kimi-code-plugin-codex](https://github.com/HOOLC/kimi-code-plugin-codex)
