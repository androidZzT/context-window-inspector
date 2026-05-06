<div align="center">
  <img src="docs/assets/hero.png" alt="Context Window Inspector" width="100%" />
</div>

<h1 align="center">Context Window Inspector</h1>

<p align="center">
  <a href="https://github.com/androidZzT/context-window-inspector/releases"><img src="https://img.shields.io/github/v/release/androidZzT/context-window-inspector?display_name=tag" alt="Release" /></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT License" /></a>
  <a href="https://github.com/androidZzT/context-window-inspector/stargazers"><img src="https://img.shields.io/github/stars/androidZzT/context-window-inspector?style=social" alt="Stars" /></a>
</p>

<p align="center">
  Read your Claude Code and Codex session logs locally. See <strong>where the tokens went</strong> — by bucket, by request, with prompt-cache and API-equivalent cost.
</p>

<p align="center">
  <strong>English</strong> · <a href="README.zh-CN.md">简体中文</a>
</p>

---

## Why

You're running Claude Code or Codex. The context bar creeps toward 80%, the agent slows down, and you have no idea what's actually in there. Tool results? An MCP server you forgot you enabled? Six months of summaries?

`cw-inspect` reads the same local JSONL transcripts the CLI already writes, then tells you:

- **Exact** input / cached / cache-write / cache-read / output / reasoning tokens (from the recorded `usage` field — not estimated).
- **Approximate** attribution by bucket: tool results, assistant messages, tool calls, system prompts, summaries, hooks, skills, MCP tools.
- **API-equivalent cost** per request and per session, using public model prices.

No API key. No network calls. Just the files already on your disk.

> ⭐ If this saves you a "where did my context go?" investigation, a star helps other Claude Code and Codex users find it.

## Statusline at a glance

<div align="center">
  <img src="docs/assets/statusline.png" alt="cw-inspect statusline output" width="100%" />
</div>

A one-line, colored bar you can drop into Claude Code's `statusLine` or print from your shell. The widest segment is usually `tool` — that's the signal.

Screenshots are representative terminal renderings. Live values and table widths vary by session, model, terminal width, and current transcript contents.

## Full report

<div align="center">
  <img src="docs/assets/report.png" alt="cw-inspect markdown report" width="100%" />
</div>

Markdown by default, JSON with `--json`. Pipe it anywhere.

## Install

Install the CLI from the latest release:

```bash
python3 -m pip install \
  "context-window-inspector @ https://github.com/androidZzT/context-window-inspector/releases/download/v0.1.0/context_window_inspector-0.1.0-py3-none-any.whl"
```

Or install the CLI from a checkout:

```bash
git clone https://github.com/androidZzT/context-window-inspector.git
cd context-window-inspector
python3 -m pip install -e .
```

Requires Python 3.10+. Zero runtime dependencies.

The wheel installs the `cw-inspect` CLI. The Codex plugin below is a repo-local marketplace plugin, so keep a source checkout when you want Codex to load it.

## Usage

Inspect the most recent session:

```bash
cw-inspect claude --latest
cw-inspect codex  --latest
```

Pick a specific session by id prefix or path:

```bash
cw-inspect claude --session 137d4ea4
cw-inspect codex  --session ~/.codex/sessions/.../rollout-XXXX.jsonl
```

Useful flags:

| Flag | What it does |
|---|---|
| `--json` | Machine-readable output |
| `--all-turns` | Include every per-turn usage event |
| `--latest` | Pick the newest session in `~/.claude/projects` or `~/.codex/sessions` |

## Statusline integration

Print the compact bar yourself:

```bash
cw-inspect statusline claude --latest
cw-inspect statusline codex  --latest --no-color --ascii
```

Wire it into the CLI you already use:

```bash
cw-inspect install-statusline claude   # wraps ~/.claude/statusline.sh
cw-inspect install-statusline codex    # writes ~/.codex/statusline-cwi.sh + enables native items
cw-inspect install-statusline all
```

Notes:

- **Claude Code** supports command-driven status lines, so the installer wraps your existing `statusline.sh` and appends the context split.
- **Codex** currently only accepts built-in `[tui].status_line` identifiers. The installer enables native `context-used` and `used-tokens`, and writes `~/.codex/statusline-cwi.sh` for the detailed breakdown — call it from your terminal prompt or a tmux status bar. Restart Codex (or open `/statusline`) after installing.

## Codex plugin (MCP)

`plugins/context-window-inspector/` ships a Codex plugin that exposes a `get_codex_context_window` MCP tool, so Codex itself can answer "what's filling my context window?" mid-session.

The plugin is loaded from this repository checkout; it is not installed into Codex by the Python wheel.

Add to `~/.codex/config.toml`:

```toml
[marketplaces.context-window-inspector]
source_type = "local"
source = "/path/to/context-window-inspector"

[plugins."context-window-inspector@context-window-inspector"]
enabled = true
```

Restart Codex. Ask the agent. It can return Markdown, the compact statusline string, or JSON.

## How attribution works

Two layers, kept separate on purpose:

**1. Exact tokens — from the provider, not us.**

| Provider | Source field |
|---|---|
| Codex | `event_msg.token_count.info` |
| Claude Code | assistant `message.usage` |

If the provider didn't record it, we don't show it.

**2. Bucket attribution — observable payload, not a tokenizer guess.**

For each transcript record we count bytes and characters and bin them into buckets (`tool_results`, `assistant_messages`, `tool_calls`, `system_or_base_instructions`, `summaries`, `developer_or_mode_instructions`, `mcp_or_dynamic_tools`, `hooks`, `skills`, `user_messages`). The split percentages allocate the **latest exact token count** across buckets weighted by byte size, so they're approximate by design. We don't run a tokenizer.

For Claude Code statuslines, the context percentage uses Claude Code's own input-only formula: `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`.

Hook attribution is deliberately narrow. Hook execution logs, echoed tool inputs, and debug stdout are **not** counted as context. Only `additionalContext`, `systemMessage`, stdout from context-bearing prompt/session events, and blocking errors land in the `hooks` bucket.

## Cost model

Reports include an API-equivalent cost when a public price is configured for the model. Read this as "what would this look like on the API meter," not as "what your subscription will be billed."

- **OpenAI / Codex**: `cached_input_tokens` is priced as the cached subset of `input_tokens`. `reasoning_output_tokens` is treated as a detail of `output_tokens`, not an extra charge.
- **Claude**: `cache_creation_input_tokens`, `cache_read_input_tokens`, and `output_tokens` are priced separately. When Claude reports `cache_creation.ephemeral_5m_input_tokens` and `ephemeral_1h_input_tokens`, each duration uses its own cache-write rate.

Public price tables live in [`src/context_window_inspector/pricing.py`](src/context_window_inspector/pricing.py). PRs welcome when prices change.

## What this is not

- Not a billing system. Estimates can drift from your invoice.
- Not a tokenizer. Bucket splits are byte-weighted approximations.
- Not a cloud service. Everything runs against files on your machine.

## Project layout

```
src/context_window_inspector/
  cli.py          # argparse entry point
  claude.py       # Claude Code JSONL parser
  codex.py        # Codex JSONL parser
  models.py       # ExactUsage / SessionReport / bucket types
  pricing.py      # public price tables, cost estimator
  reporting.py    # markdown + JSON renderers
  statusline.py   # compact bar renderer
  install.py      # statusline installers
plugins/
  context-window-inspector/   # Codex MCP plugin
tests/                          # parser, pricing, statusline, plugin tests
```

## Contributing

```bash
python3 -m pytest
PYTHONPATH=src python3 -m context_window_inspector codex --latest
```

See [`AGENTS.md`](AGENTS.md) for module conventions. Keep parsing, aggregation, and rendering in separate modules; provider-specific transcript handling stays out of the CLI layer.

Issues and PRs welcome. If a parser drops a field your provider records, open an issue with a redacted snippet and which CLI version produced it.

## License

MIT — see [LICENSE](LICENSE).
