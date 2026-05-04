# Repository Guidelines

## Project Structure & Module Organization

This repository contains a Python CLI for inspecting Claude Code and Codex context window usage from local session logs. Application source lives under `src/context_window_inspector/`, tests live under `tests/`, and packaging/configuration lives in `pyproject.toml`.

Keep provider-specific parsing in focused modules such as `src/context_window_inspector/codex.py` and `src/context_window_inspector/claude.py`. Shared data models belong in `models.py`; formatting belongs in `reporting.py`.

## Build, Test, and Development Commands

Run commands from the repository root.

- `python3 -m pytest`: run the test suite.
- `PYTHONPATH=src python3 -m context_window_inspector codex --latest`: inspect the newest Codex session without installing.
- `PYTHONPATH=src python3 -m context_window_inspector claude --latest --json`: inspect the newest Claude Code session as JSON.
- `PYTHONPATH=src python3 -m context_window_inspector statusline codex`: render the compact context split for status bars.
- `python3 -m pip install -e .`: install the `cw-inspect` console command locally.

## Coding Style & Naming Conventions

Use Python 3.10+ with 4-space indentation and type hints. Use `snake_case` for functions, variables, and modules; use `PascalCase` for dataclasses and exceptions.

Keep parsing, aggregation, and rendering separate. Do not mix provider-specific transcript handling into the CLI layer.

## Testing Guidelines

Add tests for every parser behavior and CLI-facing output contract. Use `tests/test_codex.py` and `tests/test_claude.py` for provider-specific fixtures.

Cover missing usage fields, duplicate Claude streaming records, Codex token count events, session resolution by prefix/path, and JSON output stability.

## Commit & Pull Request Guidelines

This directory has no local Git history, so no existing commit convention can be inferred. Use concise, imperative commit messages, for example `Add Claude parser` or `Handle missing Codex usage`.

Pull requests should include a short summary, the reason for the change, test evidence, and screenshots or terminal output when behavior changes. Link related issues when available and keep PRs scoped to one logical change.

## Security & Configuration Tips

Do not commit secrets, API keys, private transcripts, or generated files containing sensitive context. Add `.env.example` for required configuration and keep real values in local `.env` files ignored by Git.
