#!/usr/bin/env python3
"""Collect a normalized Codex subscription and local token-usage record."""

from __future__ import annotations

import argparse
from contextlib import suppress
import hashlib
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from collector.common import (account_cache_path, backoff_seconds, cache_lock,
                              finite_number, local_date, read_cache, write_cache)


SCHEMA_VERSION = 1
HISTORY_DAYS = 7


def resolve_codex() -> str | None:
    """Find Codex even when Plasma was started with a minimal PATH."""
    configured = os.environ.get("CODEX_BIN", "").strip()
    candidates: list[str | Path] = []
    if configured:
        candidates.append(configured)

    on_path = shutil.which("codex")
    if on_path:
        candidates.append(on_path)

    user_home = Path.home()
    candidates.extend((
        user_home / ".local/bin/codex",
        user_home / ".local/share/mise/shims/codex",
        user_home / ".local/share/mise/installs/codex/latest/bin/codex",
        user_home / ".npm-global/bin/codex",
    ))

    for candidate in candidates:
        path = Path(candidate).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def integer(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


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
            # input_tokens from Codex is a running total that already includes
            # cached_input_tokens; report the fresh (non-cached) portion here so
            # inputTokens/cachedInputTokens/cacheWriteInputTokens/outputTokens
            # are additive, matching Claude's usage schema.
            "inputTokens": max(0, self.input - self.cached_input),
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
                    if not isinstance(event, dict):
                        continue
                    payload = event.get("payload")
                    if not isinstance(payload, dict):
                        continue
                    if event.get("type") == "turn_context":
                        model = str(payload.get("model") or payload.get("model_slug") or model)
                        continue
                    if payload.get("type") != "token_count":
                        continue
                    info = payload.get("info")
                    if not isinstance(info, dict):
                        continue
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
                    if day not in daily:
                        continue
                    prompts += 1
                    session_had_usage = True
                    add_tokens(totals, delta)
                    add_tokens(model_totals[model], delta)
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
        "historyDays": HISTORY_DAYS,
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


class RpcReader:
    """Read complete frames off-thread so partial lines cannot defeat a deadline.

    select() on a TextIOWrapper misses lines already in Python's buffer. A
    reader queue also handles responses coalesced with unsolicited notifications.
    """

    def __init__(self, proc: subprocess.Popen[str]):
        self.messages: queue.Queue[str | None] = queue.Queue()
        self.thread = threading.Thread(target=self._read, args=(proc,), daemon=True)
        self.thread.start()

    def _read(self, proc: subprocess.Popen[str]) -> None:
        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                self.messages.put(line)
        finally:
            self.messages.put(None)


def rpc_request(
    proc: subprocess.Popen[str],
    request_id: int,
    method: str,
    params: dict[str, Any] | None = None,
    timeout: float = 6,
) -> dict[str, Any]:
    assert proc.stdin is not None and proc.stdout is not None
    reader = getattr(proc, "_rpc_reader", None)
    if reader is None:
        reader = RpcReader(proc)
        proc._rpc_reader = reader
    proc.stdin.write(json.dumps({"id": request_id, "method": method, "params": params or {}}) + "\n")
    proc.stdin.flush()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            line = reader.messages.get(timeout=max(0, deadline - time.monotonic()))
        except queue.Empty:
            break
        if line is None:
            raise RpcError("Codex app-server closed its output before replying.")
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict) and message.get("id") == request_id:
            if message.get("error"):
                raise RpcError(f"{method}: {message['error']}")
            result = message.get("result")
            if not isinstance(result, dict):
                raise RpcError(f"{method}: invalid response")
            return result
    raise RpcError(f"{method} timed out after {timeout:g}s")


def iso_reset(timestamp: Any) -> str | None:
    value = integer(timestamp)
    try:
        return datetime.fromtimestamp(value, timezone.utc).isoformat() if value else None
    except (ValueError, OverflowError, OSError):
        return None


def normalize_limit(limit: dict[str, Any], bucket_name: str, window_name: str) -> dict[str, Any] | None:
    window = limit.get(window_name)
    if not isinstance(window, dict):
        return None
    percent = finite_number(window.get("usedPercent"))
    if percent is None or percent < 0:
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
        "usedPercent": percent,
        "windowMinutes": minutes or None,
        "resetsAt": iso_reset(window.get("resetsAt")),
    }


def fetch_account_usage() -> dict[str, Any]:
    codex = resolve_codex()
    if not codex:
        return {"status": "unavailable", "message": "The codex command was not found.", "limits": []}
    proc = None
    # stderr must be drained too: a full diagnostic pipe can stall the server.
    diagnostics = tempfile.TemporaryFile()
    try:
        proc = subprocess.Popen(
            [codex, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=diagnostics, text=True, encoding="utf-8", errors="replace", start_new_session=True,
        )
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
        account_result = rpc_request(proc, 2, "account/read", {"refreshToken": True}, timeout=15)
        account = account_result.get("account")
        if not isinstance(account, dict):
            return {"status": "unavailable", "message": "Sign in to Codex to see subscription limits.", "limits": []}
        if account.get("type") == "apiKey":
            return {"status": "unavailable", "message": "Codex uses an API key; subscription limits require a ChatGPT login.", "authType": "apiKey", "limits": []}
        limits_result = rpc_request(proc, 3, "account/rateLimits/read", timeout=15)
        try:
            activity_result = rpc_request(proc, 4, "account/usage/read", timeout=5)
        except RpcError:
            activity_result = {}

        primary_bucket = limits_result.get("rateLimits")
        primary_bucket = primary_bucket if isinstance(primary_bucket, dict) else {}
        buckets = limits_result.get("rateLimitsByLimitId")
        if not isinstance(buckets, dict) or not buckets:
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
            "status": "ok" if limits else "unavailable",
            "message": "" if limits else "Codex returned no subscription usage windows.",
            "plan": account.get("planType") or primary_bucket.get("planType"),
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
        if proc is not None:
            # npm launchers can spawn a native app-server child. Stop the
            # whole private process group so its pipes do not remain open.
            with suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGTERM)
            if proc.poll() is None:
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    with suppress(ProcessLookupError):
                        os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
            reader = getattr(proc, "_rpc_reader", None)
            if reader is not None:
                reader.thread.join(timeout=1)
            if proc.stdin is not None:
                with suppress(OSError):
                    proc.stdin.close()
            if proc.stdout is not None:
                proc.stdout.close()
        diagnostics.close()


def auth_cache_identity(codex_home: Path) -> str:
    """Use stable account metadata; the app-server rotates tokens on reads."""
    try:
        data = json.loads((codex_home / "auth.json").read_text())
        if not isinstance(data, dict):
            return "no-saved-auth"
        tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else {}
        return hashlib.sha256(json.dumps([
            data.get("auth_mode"), tokens.get("account_id"), data.get("OPENAI_API_KEY")
        ], sort_keys=True).encode()).hexdigest()
    except (OSError, ValueError):
        return "no-saved-auth"


def cached_account_usage(codex_home: Path) -> dict[str, Any]:
    """Throttle account RPCs; their upstream HTTP headers are not exposed.

    Do not confuse the ChatGPT allowance's resetsAt with an HTTP request-rate
    reset. A full subscription window does not prohibit reading its status.
    """
    path = account_cache_path(codex_home, "codex")
    identity = auth_cache_identity(codex_home)
    base = {"status": "error", "message": "Codex account lookup is cooling down.", "limits": []}
    try:
        with cache_lock(path):
            cache = read_cache(path, identity)
            saved = cache.get("account") if isinstance(cache.get("account"), dict) else {}
            now = time.time()
            if (finite_number(cache.get("retryAt")) or 0) > now:
                return {**base, **saved, "status": "error", "message": cache.get("message") or base["message"]}
            if (finite_number(cache.get("nextRequestAt")) or 0) > now:
                return saved or base
            if not write_cache(path, {**cache, "nextRequestAt": now + 300}, identity):
                return {**base, **saved, "status": "error", "message": "Cannot save Codex's request schedule; account lookup deferred."}
            result = fetch_account_usage()
            completed = time.time()
            if result["status"] == "ok":
                write_cache(path, {"account": result, "fetchedAt": completed, "nextRequestAt": completed + 300}, identity)
                return result
            message = result.get("message") or base["message"]
            if saved:
                message += " Showing the last successful limits."
            failures = integer(cache.get("failureCount")) + 1
            retry_at = completed + backoff_seconds(failures, 300)
            write_cache(path, {"account": saved, "fetchedAt": cache.get("fetchedAt", 0), "nextRequestAt": retry_at, "retryAt": retry_at, "message": message, "failureCount": failures}, identity)
            return {**saved, **result, "limits": saved.get("limits", result["limits"]), "message": message}
    except OSError:
        cache = read_cache(path, identity)
        saved = cache.get("account") if isinstance(cache.get("account"), dict) else {}
        return {**base, **saved, "status": "error", "message": "Codex lookup is busy or its request cache is unavailable. Retrying on the next refresh."}


def collect(codex_home: Path, skip_remote: bool = False, history_days: int = 30) -> dict[str, Any]:
    local = scan_local_usage(codex_home, history_days)
    account = (
        {"status": "skipped", "message": "Account lookup skipped.", "limits": []}
        if skip_remote
        else cached_account_usage(codex_home)
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
