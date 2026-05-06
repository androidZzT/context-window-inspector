---
name: context-window
description: Inspect Codex context-window usage, token budget, prompt-cache impact, or what is filling the current coding-agent context.
---

# Context Window Inspector

Use this skill when the user asks about Codex context usage, token budget, context-window contents, what is consuming context, tool-call or assistant-message share, compaction pressure, or API-equivalent cost.

Call the `get_codex_context_window` MCP tool from the `context-window-inspector` plugin.

Recommended calls:

- For a readable answer: `get_codex_context_window({"format":"summary"})`
- For a compact status bar: `get_codex_context_window({"format":"statusline","top":6,"width":160})`
- For structured data: `get_codex_context_window({"format":"json"})`

Explain that exact token totals come from Codex `token_count` events, while bucket attribution is estimated from observable transcript payload sizes.
