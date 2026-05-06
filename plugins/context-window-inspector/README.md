# Context Window Inspector Plugin

This Codex plugin exposes a local MCP tool for inspecting Codex context-window usage from local session logs.

## Install

Add this repo as a local marketplace in `~/.codex/config.toml`:

```toml
[marketplaces.context-window-inspector]
source_type = "local"
source = "/path/to/context-window-inspector"

[plugins."context-window-inspector@context-window-inspector"]
enabled = true
```

Restart Codex after changing the config.

## Tool

- `get_codex_context_window`: returns exact token usage, estimated bucket attribution, compact statusline output, or JSON for the latest Codex session.

## Manual MCP Smoke Test

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_codex_context_window","arguments":{"format":"statusline"}}}' \
  | (cd plugins/context-window-inspector && python3 scripts/context_window_mcp.py)
```

The plugin reads local Codex JSONL transcripts only. It does not send transcript content to a remote service.
