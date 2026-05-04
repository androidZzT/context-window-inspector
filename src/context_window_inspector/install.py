from __future__ import annotations

import json
import os
import stat
from datetime import datetime
from pathlib import Path

from .statusline import repo_root


def install_claude_statusline(home: Path | None = None) -> list[str]:
    root = home or Path.home()
    claude_dir = root / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    wrapper = claude_dir / "statusline-cwi.sh"
    settings = claude_dir / "settings.json"
    _write_executable(wrapper, _claude_wrapper())

    data: dict = {}
    if settings.exists():
        _backup(settings)
        try:
            loaded = json.loads(settings.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = {}
        if isinstance(loaded, dict):
            data = loaded
    data["statusLine"] = {
        "type": "command",
        "command": 'bash "$HOME/.claude/statusline-cwi.sh"',
        "padding": 0,
    }
    settings.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return [
        f"installed Claude Code wrapper: {wrapper}",
        f"updated Claude Code settings: {settings}",
    ]


def install_codex_statusline(home: Path | None = None) -> list[str]:
    root = home or Path.home()
    codex_dir = root / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    wrapper = codex_dir / "statusline-cwi.sh"
    config = codex_dir / "config.toml"
    _write_executable(wrapper, _codex_wrapper())
    if config.exists():
        _backup(config)
        text = config.read_text(encoding="utf-8")
    else:
        text = ""
    config.write_text(_with_codex_native_statusline(text), encoding="utf-8")
    return [
        f"installed Codex split command: {wrapper}",
        f"updated Codex native status_line items: {config}",
        "Restart Codex or use /statusline to reload native items in the TUI.",
        "Codex CLI currently accepts built-in status_line identifiers only; run the wrapper directly for the detailed split.",
    ]


def _claude_wrapper() -> str:
    project = repo_root()
    return f"""#!/bin/sh
input=$(cat)
project={_sh_quote(str(project))}
base_script="$HOME/.claude/statusline.sh"
split=$(printf "%s" "$input" | PYTHONPATH="$project/src${{PYTHONPATH:+:$PYTHONPATH}}" python3 -m context_window_inspector statusline claude --stdin --no-model --width "${{COLUMNS:-140}}" 2>/dev/null)

if [ -x "$base_script" ]; then
  base=$(printf "%s" "$input" | bash "$base_script" 2>/dev/null)
else
  base=""
fi

sep=" \\033[2m│\\033[0m "
if [ -n "$base" ]; then
  first=$(printf "%b" "$base" | sed -n '1p')
  rest=$(printf "%b" "$base" | sed '1d')
  if [ -n "$split" ]; then
    printf "%b%b%b" "$first" "$sep" "$split"
  else
    printf "%b" "$first"
  fi
  [ -n "$rest" ] && printf "\\n%b" "$rest"
  printf "\\n"
else
  printf "%b\\n" "$split"
fi
"""


def _codex_wrapper() -> str:
    project = repo_root()
    return f"""#!/bin/sh
project={_sh_quote(str(project))}
PYTHONPATH="$project/src${{PYTHONPATH:+:$PYTHONPATH}}" exec python3 -m context_window_inspector statusline codex --width "${{COLUMNS:-120}}" "$@"
"""


def _with_codex_native_statusline(text: str) -> str:
    desired = 'status_line = ["model-with-reasoning", "current-dir", "git-branch", "context-used", "used-tokens"]'
    lines = text.splitlines()
    if not lines:
        return f"[tui]\n{desired}\n"

    output: list[str] = []
    in_tui = False
    replaced = False
    saw_tui = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_tui and not replaced:
                output.append(desired)
                replaced = True
            in_tui = stripped == "[tui]"
            saw_tui = saw_tui or in_tui
        if in_tui and stripped.startswith("status_line"):
            output.append(desired)
            replaced = True
            continue
        output.append(line)

    if in_tui and not replaced:
        output.append(desired)
    elif not saw_tui:
        if output and output[-1].strip():
            output.append("")
        output.extend(["[tui]", desired])
    return "\n".join(output) + "\n"


def _write_executable(path: Path, content: str) -> None:
    if path.exists():
        _backup(path)
    path.write_text(content, encoding="utf-8")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _backup(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup = path.with_name(f"{path.name}.bak-cwi-{stamp}")
    backup.write_bytes(path.read_bytes())
    return backup


def _sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"
