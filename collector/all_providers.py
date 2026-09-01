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


def collect(skip_remote: bool = False, history_days: int = 30) -> dict:
    providers = []
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    claude_home = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    if shutil.which("codex") or codex_home.exists():
        providers.append(collect_codex(codex_home, skip_remote, history_days))
    if shutil.which("claude") or claude_home.exists():
        providers.append(collect_claude(claude_home, skip_remote, history_days))
    return {
        "schemaVersion": 1,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "providers": providers,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-only", action="store_true")
    parser.add_argument("--history-days", type=int, default=30)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    result = collect(args.local_only, max(7, args.history_days))
    json.dump(result, sys.stdout, indent=2 if args.pretty else None, separators=None if args.pretty else (",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
