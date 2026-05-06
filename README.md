# Context Window Inspector

[![Release](https://img.shields.io/github/v/release/androidZzT/context-window-inspector?display_name=tag)](https://github.com/androidZzT/context-window-inspector/releases)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Inspect Claude Code and OpenAI Codex context-window usage, token attribution, prompt-cache usage, and API-equivalent cost from local session logs.

`context-window-inspector` is a local Python CLI for developers who want to understand what is filling an LLM coding agent's context window. It separates exact token usage reported by Claude Code or Codex from approximate payload attribution derived from local transcripts.

If this helps you debug LLM context budgets, a GitHub star helps other Claude Code and Codex users find it.

## Features

- Inspect Claude Code and Codex local JSONL transcripts.
- Show exact input, cached input, cache write/read, output, reasoning, and total token counts.
- Estimate context-window attribution by bucket: assistant messages, tool calls, tool results, system prompts, summaries, hooks, skills, and MCP tools.
- Render compact statusline output for coding-agent terminals.
- Estimate API-equivalent cost for supported OpenAI and Anthropic models.

## Install

Install the CLI from the latest GitHub release:

```bash
python3 -m pip install "context-window-inspector @ https://github.com/androidZzT/context-window-inspector/releases/download/v0.1.0/context_window_inspector-0.1.0-py3-none-any.whl"
```

Or install the CLI from a local checkout:

```bash
python3 -m pip install -e .
```

The wheel installs the `cw-inspect` CLI. The Codex plugin below is a repo-local marketplace plugin, so keep a source checkout when you want Codex to load it.

## Usage

```bash
python3 -m context_window_inspector codex --latest
python3 -m context_window_inspector claude --latest
python3 -m context_window_inspector statusline codex

# After installing the package:
cw-inspect codex --latest
cw-inspect codex --session <session-id-or-path>
cw-inspect claude --latest
cw-inspect claude --session <session-id-or-path> --json
cw-inspect statusline claude --stdin
```

The default report is Markdown. Use `--json` for machine-readable output and `--all-turns` to include every exact usage event.

## Status Line

The status line renderer prints a compact, colored progress bar segmented by estimated window share:

```bash
cw-inspect statusline codex --latest
cw-inspect statusline claude --latest --no-color --ascii
```

Example shape:

```text
gpt-5.5 | ctx 52.3% [tool 20.3][sum 14.6][asst 9.2][call 5.7][sys 2.5][+ 0.1] 135K/258K
```

Install helpers:

```bash
cw-inspect install-statusline claude
cw-inspect install-statusline codex
```

Claude Code supports command status lines, so the installer wraps the existing `~/.claude/statusline.sh` and appends the context split. Codex CLI currently supports built-in `[tui].status_line` identifiers only; the installer enables native `context-used` and `used-tokens`, and installs `~/.codex/statusline-cwi.sh` for the detailed split.

Codex TUI reads status line items when the interface starts or when the `/statusline` menu saves a new selection. After running the installer, restart Codex or open `/statusline` to apply the native items. The detailed `asst/tool/call/sum` split is available from `~/.codex/statusline-cwi.sh`; it is not injected into the Codex TUI status line because Codex does not currently accept external status line commands.

## Codex Plugin

This repo also ships a local Codex plugin at `plugins/context-window-inspector/`. The plugin exposes a `get_codex_context_window` MCP tool so Codex can answer questions such as "what is filling my context window?" from inside a session.

The plugin is loaded from this repository checkout; it is not installed into Codex by the Python wheel.

To install it as a local marketplace, add this to `~/.codex/config.toml`:

```toml
[marketplaces.context-window-inspector]
source_type = "local"
source = "/path/to/context-window-inspector"

[plugins."context-window-inspector@context-window-inspector"]
enabled = true
```

Restart Codex after editing the config. The plugin can return a readable summary, compact statusline text, or JSON. It does not add a custom TUI statusline segment because Codex currently only supports built-in statusline items.

## Attribution Model

Exact token values come only from recorded usage fields:

- Codex: `event_msg.token_count.info`
- Claude Code: assistant `message.usage`

Everything else is reported as observable payload size by bucket, using record counts, character counts, byte counts, and examples. The CLI does not estimate tokens by default.

For Claude Code status lines, context percentage follows Claude Code's official input-only formula: `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`. Hook attribution is deliberately narrow: hook execution logs, echoed tool inputs, and debug stdout are not counted as context. Only `additionalContext`, `systemMessage`, stdout from context-bearing prompt/session events, and blocking errors are attributed to `hooks`.

## Cost Model

Reports include an estimated API-equivalent cost when a public price is configured for the recorded model. This is not an authoritative bill for Codex subscriptions, Claude Pro/Max, or provider-specific enterprise terms.

- OpenAI/Codex: `cached_input_tokens` is priced as the cached subset of `input_tokens`; `reasoning_output_tokens` is treated as a detail of `output_tokens`, not an extra charge.
- Claude: `cache_creation_input_tokens`, `cache_read_input_tokens`, and `output_tokens` are priced separately. When Claude records `cache_creation.ephemeral_5m_input_tokens` and `ephemeral_1h_input_tokens`, those durations use their distinct cache write rates.
