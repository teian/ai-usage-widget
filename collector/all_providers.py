#!/usr/bin/env python3
"""Collect every locally available AI usage provider."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from collector.claude import collect as collect_claude, resolve_claude
from collector.codex import collect as collect_codex, resolve_codex


def collect(skip_remote: bool = False, history_days: int = 30, enabled: set[str] | None = None) -> dict:
    providers = []
    if enabled is None:
        enabled = {"codex", "claude"}
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    claude_home = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    available = {
        "codex": bool(resolve_codex()),
        "claude": bool(resolve_claude()),
    }
    # A leftover configuration directory is not proof that its CLI is still
    # installed. Only include providers the user can actually run.
    for provider, name, home, collector in (
        ("codex", "Codex", codex_home, collect_codex),
        ("claude", "Claude Code", claude_home, collect_claude),
    ):
        if provider not in enabled or not available[provider]:
            continue
        try:
            providers.append(collector(home, skip_remote, history_days))
        except Exception as exc:
            # A provider failure must not invalidate the other provider's JSON
            # or make the entire applet refresh fail.
            print(f"{provider} collection failed: {type(exc).__name__}", file=sys.stderr)
            providers.append({
                "schemaVersion": 1,
                "provider": {"id": provider, "name": name},
                "updatedAt": datetime.now(timezone.utc).isoformat(),
                "account": {"status": "error", "message": f"{name} collection failed ({type(exc).__name__}).", "limits": []},
                "localActivity": {"scope": "machine", "totals": {"inputTokens": 0, "cachedInputTokens": 0, "cacheWriteInputTokens": 0, "outputTokens": 0, "totalTokens": 0, "prompts": 0, "sessions": 0}, "daily": [], "models": []},
            })
    return {
        "schemaVersion": 1,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "availableProviders": available,
        "providers": providers,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-only", action="store_true")
    parser.add_argument("--history-days", type=int, default=30)
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--provider", action="append", choices=("codex", "claude"), dest="providers")
    args = parser.parse_args(argv)
    result = collect(args.local_only, max(7, args.history_days), set(args.providers) if args.providers else None)
    json.dump(result, sys.stdout, indent=2 if args.pretty else None, separators=None if args.pretty else (",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
