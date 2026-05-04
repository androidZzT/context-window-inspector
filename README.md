# Context Window Inspector

`context-window-inspector` is a local CLI for inspecting what is observable in Claude Code and Codex session context. It separates exact token usage reported by the tools from payload-size attribution derived from local transcripts.

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
gpt-5.5 | ctx 26.2% [asst10.1====|tool8.1===|call3.1|sum----------------] 68K/258K
```

Install helpers:

```bash
cw-inspect install-statusline claude
cw-inspect install-statusline codex
```

Claude Code supports command status lines, so the installer wraps the existing `~/.claude/statusline.sh` and appends the context split. Codex CLI currently supports built-in `[tui].status_line` identifiers only; the installer enables native `context-used` and `used-tokens`, and installs `~/.codex/statusline-cwi.sh` for the detailed split.

Codex TUI reads status line items when the interface starts or when the `/statusline` menu saves a new selection. After running the installer, restart Codex or open `/statusline` to apply the native items. The detailed `asst/tool/call/sum` split is available from `~/.codex/statusline-cwi.sh`; it is not injected into the Codex TUI status line because Codex does not currently accept external status line commands.

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
