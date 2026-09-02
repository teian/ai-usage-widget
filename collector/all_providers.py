#!/usr/bin/env python3
"""Collect every locally available AI usage provider."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from collector.claude import collect as collect_claude
from collector.codex import collect as collect_codex


def collect(skip_remote: bool = False, history_days: int = 30, enabled: set[str] | None = None) -> dict:
    providers = []
    if enabled is None:
        enabled = {"codex", "claude"}
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    claude_home = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    available = {
        "codex": bool(shutil.which("codex")),
        "claude": bool(shutil.which("claude")),
    }
    # A leftover configuration directory is not proof that its CLI is still
    # installed. Only include providers the user can actually run.
    if "codex" in enabled and available["codex"]:
        providers.append(collect_codex(codex_home, skip_remote, history_days))
    if "claude" in enabled and available["claude"]:
        providers.append(collect_claude(claude_home, skip_remote, history_days))
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
