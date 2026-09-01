#!/usr/bin/env python3
"""Collect a normalized Codex subscription and local token-usage record."""

from __future__ import annotations

import argparse
import json
import os
import select
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
HISTORY_DAYS = 7


def integer(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def local_date(value: Any, fallback_mtime: float) -> str:
    if isinstance(value, (int, float)):
        stamp = float(value) / 1000 if value > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(stamp).astimezone().date().isoformat()
    if value:
        try:
            text = str(value).replace("Z", "+00:00")
            return datetime.fromisoformat(text).astimezone().date().isoformat()
        except ValueError:
            pass
    return datetime.fromtimestamp(fallback_mtime).astimezone().date().isoformat()


@dataclass(frozen=True)
class Tokens:
    input: int = 0
    cached_input: int = 0
    cache_write: int = 0
    output: int = 0

    @classmethod
    def from_usage(cls, usage: dict[str, Any]) -> "Tokens":
        return cls(
            input=integer(usage.get("input_tokens")),
            cached_input=integer(usage.get("cached_input_tokens")),
            cache_write=integer(usage.get("cache_write_input_tokens")),
            output=integer(usage.get("output_tokens")),
        )

    def delta(self, earlier: "Tokens") -> "Tokens":
        return Tokens(
            max(0, self.input - earlier.input),
            max(0, self.cached_input - earlier.cached_input),
            max(0, self.cache_write - earlier.cache_write),
            max(0, self.output - earlier.output),
        )

    @property
    def total(self) -> int:
        # Cached input is already included in input_tokens.
        return self.input + self.output

    def as_dict(self) -> dict[str, int]:
        return {
            "inputTokens": self.input,
            "cachedInputTokens": self.cached_input,
            "cacheWriteInputTokens": self.cache_write,
            "outputTokens": self.output,
            "totalTokens": self.total,
        }


def add_tokens(target: dict[str, int], tokens: Tokens) -> None:
    values = tokens.as_dict()
    for key, value in values.items():
        target[key] = target.get(key, 0) + value


def session_files(codex_home: Path, history_days: int) -> Iterable[Path]:
    cutoff = time.time() - history_days * 86400
    for directory in (codex_home / "sessions", codex_home / "archived_sessions"):
        if not directory.is_dir():
            continue
        for path in directory.rglob("*.jsonl"):
            try:
                if path.stat().st_mtime >= cutoff:
                    yield path
            except OSError:
                continue


def scan_local_usage(codex_home: Path, history_days: int = 30) -> dict[str, Any]:
    today = datetime.now().astimezone().date()
    dates = [(today - timedelta(days=offset)).isoformat() for offset in range(HISTORY_DAYS - 1, -1, -1)]
    daily: dict[str, dict[str, Any]] = {
        day: {"date": day, "tokens": 0, "prompts": 0, "sessions": set()} for day in dates
    }
    totals: dict[str, int] = {}
    model_totals: dict[str, dict[str, int]] = defaultdict(dict)
    all_sessions: set[str] = set()
    prompts = 0

    for path in session_files(codex_home, history_days):
        model = "codex"
        previous = Tokens()
        session_had_usage = False
        try:
            mtime = path.stat().st_mtime
            with path.open(encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    try:
                        event = json.loads(line)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    payload = event.get("payload") or {}
                    if event.get("type") == "turn_context":
                        model = str(payload.get("model") or payload.get("model_slug") or model)
                        continue
                    if payload.get("type") != "token_count":
                        continue
                    info = payload.get("info") or {}
                    cumulative_raw = info.get("total_token_usage")
                    last_raw = info.get("last_token_usage")
                    if isinstance(cumulative_raw, dict):
                        cumulative = Tokens.from_usage(cumulative_raw)
                        # A lower cumulative count indicates a new accounting segment.
                        if cumulative.input < previous.input or cumulative.output < previous.output:
                            delta = cumulative
                        else:
                            delta = cumulative.delta(previous)
                        previous = cumulative
                    elif isinstance(last_raw, dict):
                        delta = Tokens.from_usage(last_raw)
                    else:
                        continue
                    if delta.total == 0:
                        continue
                    day = local_date(event.get("timestamp"), mtime)
                    prompts += 1
                    session_had_usage = True
                    add_tokens(totals, delta)
                    add_tokens(model_totals[model], delta)
                    if day in daily:
                        daily[day]["tokens"] += delta.total
                        daily[day]["prompts"] += 1
                        daily[day]["sessions"].add(str(path))
        except OSError:
            continue
        if session_had_usage:
            all_sessions.add(str(path))

    days = []
    for day in dates:
        row = daily[day]
        days.append({
            "date": day,
            "tokens": row["tokens"],
            "prompts": row["prompts"],
            "sessions": len(row["sessions"]),
        })
    return {
        "scope": "machine",
        "historyDays": history_days,
        "totals": {
            **{key: totals.get(key, 0) for key in Tokens().as_dict()},
            "prompts": prompts,
            "sessions": len(all_sessions),
        },
        "daily": days,
        "models": [
            {"model": name, **values}
            for name, values in sorted(model_totals.items(), key=lambda item: item[1].get("totalTokens", 0), reverse=True)
        ],
    }


class RpcError(RuntimeError):
    pass


def rpc_request(
    proc: subprocess.Popen[str],
    request_id: int,
    method: str,
    params: dict[str, Any] | None = None,
    timeout: float = 6,
) -> dict[str, Any]:
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write(json.dumps({"id": request_id, "method": method, "params": params or {}}) + "\n")
    proc.stdin.flush()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            detail = ""
            if proc.stderr is not None:
                detail = proc.stderr.read(2048).strip()
            raise RpcError(detail or f"Codex app-server exited with status {proc.returncode}")
        ready, _, _ = select.select([proc.stdout], [], [], min(0.25, deadline - time.monotonic()))
        if not ready:
            continue
        line = proc.stdout.readline()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("id") == request_id:
            if message.get("error"):
                raise RpcError(f"{method}: {message['error']}")
            return message.get("result") or {}
    raise RpcError(f"{method} timed out after {timeout:g}s")


def iso_reset(timestamp: Any) -> str | None:
    value = integer(timestamp)
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value else None


def normalize_limit(limit: dict[str, Any], bucket_name: str, window_name: str) -> dict[str, Any] | None:
    window = limit.get(window_name)
    if not isinstance(window, dict) or window.get("usedPercent") is None:
        return None
    minutes = integer(window.get("windowDurationMins"))
    if minutes == 10080:
        label = "Weekly"
    elif minutes and minutes % 60 == 0:
        label = f"{minutes // 60}-hour"
    elif minutes:
        label = f"{minutes}-minute"
    else:
        label = window_name.title()
    name = limit.get("limitName")
    if name and str(name).lower() not in {"codex", bucket_name.lower()}:
        label = f"{name} · {label}"
    return {
        "id": f"{bucket_name}:{window_name}",
        "label": label,
        "usedPercent": float(window["usedPercent"]),
        "windowMinutes": minutes or None,
        "resetsAt": iso_reset(window.get("resetsAt")),
    }


def fetch_account_usage() -> dict[str, Any]:
    codex = shutil.which("codex")
    if not codex:
        return {"status": "unavailable", "message": "The codex command was not found.", "limits": []}
    proc = subprocess.Popen(
        [codex, "app-server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        initialized = rpc_request(
            proc,
            1,
            "initialize",
            {"clientInfo": {"name": "ai-usage-widget", "version": "0.1.0"}},
            timeout=8,
        )
        assert proc.stdin is not None
        proc.stdin.write(json.dumps({"method": "initialized", "params": {}}) + "\n")
        proc.stdin.flush()
        account_result = rpc_request(proc, 2, "account/read", timeout=5)
        limits_result = rpc_request(proc, 3, "account/rateLimits/read", timeout=5)
        try:
            activity_result = rpc_request(proc, 4, "account/usage/read", timeout=5)
        except RpcError:
            activity_result = {}

        account = account_result.get("account") or {}
        buckets = limits_result.get("rateLimitsByLimitId")
        if not isinstance(buckets, dict) or not buckets:
            primary_bucket = limits_result.get("rateLimits") or {}
            buckets = {str(primary_bucket.get("limitId") or "codex"): primary_bucket}
        limits = []
        for bucket_name, bucket in buckets.items():
            if not isinstance(bucket, dict):
                continue
            for window_name in ("primary", "secondary"):
                normalized = normalize_limit(bucket, str(bucket_name), window_name)
                if normalized:
                    limits.append(normalized)
        return {
            "status": "ok",
            "message": "",
            "plan": account.get("planType") or (limits_result.get("rateLimits") or {}).get("planType"),
            "authType": account.get("type"),
            "limits": limits,
            "accountActivity": {
                "scope": "account",
                "summary": activity_result.get("summary"),
                "daily": activity_result.get("dailyUsageBuckets"),
            },
            "appServerVersion": initialized.get("userAgent"),
        }
    except (OSError, RpcError) as exc:
        return {"status": "error", "message": str(exc), "limits": []}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=1)


def collect(codex_home: Path, skip_remote: bool = False, history_days: int = 30) -> dict[str, Any]:
    local = scan_local_usage(codex_home, history_days)
    account = (
        {"status": "skipped", "message": "Account lookup skipped.", "limits": []}
        if skip_remote
        else fetch_account_usage()
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "provider": {"id": "codex", "name": "Codex", "icon": "utilities-terminal"},
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "account": account,
        "localActivity": local,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-only", action="store_true", help="skip Codex account and limit RPCs")
    parser.add_argument("--history-days", type=int, default=30, help="number of days of local session files to scan")
    parser.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    args = parser.parse_args(argv)
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    record = collect(codex_home, skip_remote=args.local_only, history_days=max(HISTORY_DAYS, args.history_days))
    json.dump(record, sys.stdout, indent=2 if args.pretty else None, separators=None if args.pretty else (",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
