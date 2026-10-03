#!/usr/bin/env python3
"""Collect Claude Code subscription limits and machine-local token activity."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from collector.common import (account_cache_path, backoff_seconds, cache_lock,
                              finite_number, header_retry_at, local_date,
                              read_cache, write_cache)


SCHEMA_VERSION = 1
HISTORY_DAYS = 7
USAGE_ENDPOINT = "https://api.anthropic.com/api/oauth/usage"
TOKEN_ENDPOINT = "https://platform.claude.com/v1/oauth/token"
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"


def resolve_claude() -> str | None:
    """Find Claude Code even when Plasma was started with a minimal PATH."""
    configured = os.environ.get("CLAUDE_BIN", "").strip()
    candidates: list[str | Path] = []
    if configured:
        candidates.append(configured)

    on_path = shutil.which("claude")
    if on_path:
        candidates.append(on_path)

    user_home = Path.home()
    candidates.extend((
        user_home / ".claude/local/claude",
        user_home / ".local/bin/claude",
        user_home / ".local/share/mise/shims/claude",
        user_home / ".local/share/mise/installs/claude/latest/claude",
        user_home / ".npm-global/bin/claude",
    ))

    for candidate in candidates:
        path = Path(candidate).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def integer(value: Any) -> int:
    try:
        return max(0, round(float(value or 0)))
    except (TypeError, ValueError, OverflowError):
        return 0


def transcript_files(claude_home: Path, history_days: int) -> Iterable[Path]:
    projects = claude_home / "projects"
    if not projects.is_dir():
        return
    cutoff = time.time() - history_days * 86400
    for path in projects.rglob("*.jsonl"):
        try:
            if path.stat().st_mtime >= cutoff:
                yield path
        except OSError:
            continue


def token_values(usage: dict[str, Any]) -> dict[str, int]:
    values = {
        "inputTokens": integer(usage.get("input_tokens", usage.get("inputTokens"))),
        "cachedInputTokens": integer(usage.get("cache_read_input_tokens", usage.get("cacheReadInputTokens"))),
        "cacheWriteInputTokens": integer(
            usage.get("cache_creation_input_tokens", usage.get("cacheCreationInputTokens"))
        ),
        "outputTokens": integer(usage.get("output_tokens", usage.get("outputTokens"))),
    }
    values["totalTokens"] = sum(values.values())
    return values


def add_values(target: dict[str, int], values: dict[str, int]) -> None:
    for key, value in values.items():
        target[key] = target.get(key, 0) + value


def scan_local_usage(claude_home: Path, history_days: int = 30) -> dict[str, Any]:
    today = datetime.now().astimezone().date()
    dates = [(today - timedelta(days=offset)).isoformat() for offset in range(HISTORY_DAYS - 1, -1, -1)]
    daily: dict[str, dict[str, Any]] = {
        day: {"date": day, "tokens": 0, "prompts": 0, "sessions": set()} for day in dates
    }
    totals: dict[str, int] = {}
    models: dict[str, dict[str, int]] = defaultdict(dict)
    sessions: set[str] = set()
    seen_messages: dict[str, dict[str, int]] = {}
    prompts = 0

    for path in transcript_files(claude_home, history_days):
        try:
            mtime = path.stat().st_mtime
            with path.open(encoding="utf-8", errors="replace") as handle:
                for line_number, line in enumerate(handle, 1):
                    if '"usage"' not in line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    message = event.get("message") if isinstance(event.get("message"), dict) else {}
                    if event.get("type") != "assistant" and message.get("role") != "assistant":
                        continue
                    usage = message.get("usage") or event.get("usage")
                    if not isinstance(usage, dict):
                        continue
                    message_id = message.get("id") or event.get("messageId")
                    unique_id = str(message_id) if message_id else f"{path}:{event.get('uuid') or line_number}"
                    values = token_values(usage)
                    if values["totalTokens"] == 0:
                        continue
                    model = str(message.get("model") or event.get("model") or "claude")
                    session = str(event.get("sessionId") or path)
                    day = local_date(event.get("timestamp") or message.get("timestamp"), mtime)
                    if day not in daily:
                        continue
                    previous = seen_messages.get(unique_id)
                    # Streaming entries can repeat a message ID with newer
                    # counters. Count the largest observed counters once.
                    current = {key: max(value, (previous or {}).get(key, 0)) for key, value in values.items() if key != "totalTokens"}
                    current["totalTokens"] = sum(current.values())
                    values = {key: value - (previous or {}).get(key, 0) for key, value in current.items()}
                    seen_messages[unique_id] = current
                    if values["totalTokens"] == 0:
                        continue
                    prompts += int(previous is None)
                    sessions.add(session)
                    add_values(totals, values)
                    add_values(models[model], values)
                    daily[day]["tokens"] += values["totalTokens"]
                    daily[day]["prompts"] += int(previous is None)
                    daily[day]["sessions"].add(session)
        except OSError:
            continue

    return {
        "scope": "machine",
        "historyDays": HISTORY_DAYS,
        "totals": {
            **{key: totals.get(key, 0) for key in token_values({})},
            "prompts": prompts,
            "sessions": len(sessions),
        },
        "daily": [
            {
                "date": day,
                "tokens": daily[day]["tokens"],
                "prompts": daily[day]["prompts"],
                "sessions": len(daily[day]["sessions"]),
            }
            for day in dates
        ],
        "models": [
            {"model": model, **values}
            for model, values in sorted(models.items(), key=lambda item: item[1].get("totalTokens", 0), reverse=True)
        ],
    }


def plan_label(tier: Any, subscription: Any) -> str | None:
    match = re.search(r"max_(\d+x)", str(tier or ""), re.IGNORECASE)
    if match:
        return f"Max {match.group(1)}"
    text = str(subscription or "").strip()
    return text[:1].upper() + text[1:] if text else None


def oauth_login(claude_home: Path) -> tuple[str, int, str | None]:
    try:
        data = json.loads((credential_home(claude_home) / ".credentials.json").read_text(encoding="utf-8"))
        login = data.get("claudeAiOauth") if isinstance(data, dict) else None
        login = login if isinstance(login, dict) else {}
    except (OSError, ValueError):
        return "", 0, None
    return (
        login.get("accessToken") if isinstance(login.get("accessToken"), str) else "",
        integer(login.get("expiresAt")),
        plan_label(login.get("rateLimitTier"), login.get("subscriptionType")),
    )


def credential_home(claude_home: Path) -> Path:
    configured = os.environ.get("CLAUDE_SECURESTORAGE_CONFIG_DIR")
    return Path(configured or Path.home() / ".claude").expanduser() if configured is not None else claude_home


@contextmanager
def credential_lock(claude_home: Path):
    # Claude Code uses proper-lockfile directory locks, including a legacy
    # lock beside the config directory. Cooperate with both CLI generations.
    acquired = []
    deadline = time.monotonic() + 12
    try:
        for path in (claude_home / ".oauth_refresh.lock", Path(str(claude_home.resolve()) + ".lock")):
            while True:
                try:
                    path.mkdir(mode=0o700)
                    acquired.append(path)
                    break
                except FileExistsError:
                    # Match proper-lockfile's 60-second stale threshold. An
                    # interrupted CLI can leave an empty lock directory behind.
                    try:
                        observed = path.stat()
                        if time.time() - observed.st_mtime > 60:
                            current = path.stat()
                            if (current.st_ino, current.st_mtime_ns) == (observed.st_ino, observed.st_mtime_ns):
                                path.rmdir()
                                continue
                    except FileNotFoundError:
                        continue
                    except OSError:
                        pass
                    if time.monotonic() >= deadline:
                        raise ValueError("Claude credential refresh is already in progress.")
                    time.sleep(0.05)
        yield
    finally:
        for path in reversed(acquired):
            try:
                path.rmdir()
            except OSError:
                pass


def refresh_login(claude_home: Path, rejected_token: str, response_headers: dict[str, str] | None = None) -> str:
    """Refresh a saved OAuth login, preserving rotated tokens and other fields.

    Serialize widget refreshes and reread before writing so a login changed by
    Claude Code while the request was running is never overwritten.
    """
    claude_home = credential_home(claude_home)
    path = claude_home / ".credentials.json"
    with credential_lock(claude_home):
        data = json.loads(path.read_text(encoding="utf-8"))
        login = data.get("claudeAiOauth") if isinstance(data, dict) else None
        if not isinstance(login, dict):
            raise ValueError("Claude credentials do not contain an OAuth login.")
        if login.get("accessToken") != rejected_token:
            return str(login.get("accessToken") or "")
        if not login.get("refreshToken"):
            raise ValueError("Claude's login cannot be refreshed. Run claude auth login.")
        body = {"grant_type": "refresh_token", "refresh_token": login["refreshToken"], "client_id": login.get("clientId") or OAUTH_CLIENT_ID}
        if isinstance(login.get("scopes"), list) and login["scopes"] and all(isinstance(scope, str) for scope in login["scopes"]):
            body["scope"] = " ".join(login["scopes"])
        request = urllib.request.Request(TOKEN_ENDPOINT, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as response:
            if response_headers is not None:
                response_headers.update(dict(getattr(response, "headers", {}).items()))
            result = json.load(response)
        if not isinstance(result, dict) or not isinstance(result.get("access_token"), str) or not result["access_token"] or integer(result.get("expires_in")) == 0:
            raise ValueError("Claude returned an invalid credential refresh response.")
        latest = json.loads(path.read_text(encoding="utf-8"))
        if latest != data:
            # Let Claude Code's newer credentials win, even if only metadata
            # changed; we must not replace a concurrently updated file.
            return oauth_login(claude_home)[0]
        updated = {**login, "accessToken": result["access_token"], "refreshToken": result.get("refresh_token") or login["refreshToken"], "expiresAt": int(time.time() * 1000) + integer(result["expires_in"]) * 1000}
        if isinstance(result.get("scope"), str):
            updated["scopes"] = result["scope"].split()
        if result.get("refresh_token_expires_in") is not None:
            updated["refreshTokenExpiresAt"] = int(time.time() * 1000) + integer(result["refresh_token_expires_in"]) * 1000
        data["claudeAiOauth"] = updated
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=claude_home, prefix=".ai-usage-credentials-", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(data, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return updated["accessToken"]


def reset_time(value: Any) -> str | None:
    if value is None or value == "":
        return None
    text = str(value)
    if text.isdigit():
        stamp = int(text)
        stamp = stamp / 1000 if stamp > 10_000_000_000 else stamp
        try:
            return datetime.fromtimestamp(stamp, timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return text


def used_percent(value: Any, percent_scaled: bool) -> float | None:
    number = finite_number(str(value).strip().replace("%", ""))
    if number is None:
        return None
    if number < 0:
        return None
    return min(100.0, number if percent_scaled or number > 1 else number * 100)


def fetch_limits(access_token: str, response_headers: dict[str, str] | None = None) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        USAGE_ENDPOINT,
        headers={
            "Authorization": f"Bearer {access_token}",
            "anthropic-beta": "oauth-2025-04-20",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        if response_headers is not None:
            response_headers.update(dict(response.headers.items()))
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    if not isinstance(payload, dict):
        raise ValueError("Claude returned an invalid usage response.")
    return parse_limits(payload)


CURRENCY_SYMBOLS = {"GBP": "\u00a3", "USD": "$", "EUR": "\u20ac", "JPY": "\u00a5"}


def money(amount: Any, currency: str, decimals: int) -> str:
    symbol = CURRENCY_SYMBOLS.get(currency)
    figure = f"{float(amount):,.{decimals}f}"
    return f"{symbol}{figure}" if symbol else f"{figure} {currency}".strip()


def credit_limit(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Usage credits are a shared pay-as-you-go pool; Fable and any overflow past the plan windows bill here."""
    spend = payload.get("spend") if isinstance(payload.get("spend"), dict) else None
    extra = payload.get("extra_usage") if isinstance(payload.get("extra_usage"), dict) else None
    if spend and spend.get("enabled") is not None:
        enabled = bool(spend.get("enabled"))
    elif extra:
        enabled = bool(extra.get("is_enabled")) and not extra.get("user_disabled")
    else:
        return None
    if not enabled:
        return None

    used = limit = None
    currency = ""
    decimals = 2
    if spend:
        used_block = spend.get("used") if isinstance(spend.get("used"), dict) else {}
        limit_block = spend.get("limit") if isinstance(spend.get("limit"), dict) else {}
        try:
            decimals = max(0, min(6, int(used_block.get("exponent", limit_block.get("exponent", 2)))))
            if used_block.get("amount_minor") is not None:
                used = int(used_block["amount_minor"]) / 10**decimals
            if limit_block.get("amount_minor") is not None:
                limit = int(limit_block["amount_minor"]) / 10**decimals
        except (TypeError, ValueError):
            used = limit = None
        currency = str(used_block.get("currency") or limit_block.get("currency") or "")
    if used is None and extra:
        try:
            decimals = max(0, min(6, int(extra.get("decimal_places", 2))))
            used = float(extra.get("used_credits") or 0) / 10**decimals
            limit = float(extra["monthly_limit"]) / 10**decimals if extra.get("monthly_limit") is not None else None
        except (TypeError, ValueError):
            used = None
        currency = str(extra.get("currency") or currency)
    if used is None:
        return None
    if finite_number(used) is None or (limit is not None and finite_number(limit) is None):
        return None

    percent = used_percent((spend or {}).get("percent"), True)
    if percent is None and extra:
        percent = used_percent(extra.get("utilization"), True)
    if percent is None and limit:
        percent = min(100.0, used / limit * 100)
    if percent is None:
        percent = 0.0
    detail = money(used, currency, decimals)
    if limit is not None:
        detail = f"{detail} of {money(limit, currency, decimals)}"
    return {
        "id": "credits",
        "label": "Credits",
        "usedPercent": percent,
        "windowMinutes": None,
        "resetsAt": None,
        "detail": detail,
    }


def parse_limits(payload: dict[str, Any]) -> list[dict[str, Any]]:
    session = payload.get("five_hour") if isinstance(payload.get("five_hour"), dict) else None
    weekly = payload.get("seven_day_oauth_apps") or payload.get("seven_day")
    weekly = weekly if isinstance(weekly, dict) else None
    scoped = payload.get("limits") if isinstance(payload.get("limits"), list) else []
    # The usage endpoint's utilization and percent fields are percentages.
    # Inferring the scale from the current value turns 0.4% into 40% and makes
    # a window's display jump when another window crosses 1%.
    limits: list[dict[str, Any]] = []
    for key, label, bucket in (("five_hour", "5-hour", session), ("seven_day", "Weekly", weekly)):
        if not bucket:
            continue
        percent = used_percent(bucket.get("utilization"), True)
        if percent is not None:
            limits.append({
                "id": key,
                "label": label,
                "usedPercent": percent,
                "windowMinutes": 300 if key == "five_hour" else 10080,
                "resetsAt": reset_time(bucket.get("resets_at")),
            })
    for index, item in enumerate(scoped):
        if not isinstance(item, dict):
            continue
        scope = item.get("scope") if isinstance(item.get("scope"), dict) else {}
        model = scope.get("model") if isinstance(scope.get("model"), dict) else {}
        name = str(model.get("display_name") or model.get("id") or "").strip()
        percent = used_percent(item.get("percent"), True)
        if not name or percent is None:
            continue
        kind = str(item.get("kind") or "").lower()
        window = "Weekly" if "week" in kind or "day" in kind else "5-hour" if "hour" in kind else "Limit"
        limits.append({
            "id": f"scoped:{index}",
            "label": f"{name} · {window}",
            "usedPercent": percent,
            "windowMinutes": None,
            "resetsAt": reset_time(item.get("resets_at")),
        })
    credits = credit_limit(payload)
    if credits:
        limits.append(credits)
    return limits


def usage_cache_path(claude_home: Path) -> Path:
    return account_cache_path(claude_home, "claude")


def account_usage(claude_home: Path, skip_remote: bool) -> dict[str, Any]:
    token, expires_at, plan = oauth_login(claude_home)
    base = {"plan": plan, "limits": []}
    if skip_remote:
        return {**base, "status": "skipped", "message": "Account lookup skipped."}
    if not token:
        return {**base, "status": "unavailable", "message": "Sign in to Claude Code to see subscription limits."}
    try:
        with cache_lock(usage_cache_path(claude_home)):
            return poll_account_usage(claude_home, token, expires_at, plan)
    except OSError:
        cache = read_cache(usage_cache_path(claude_home), token)
        saved = cache.get("account") if isinstance(cache.get("account"), dict) else {}
        return {**base, **saved, "status": "error", "message": "Claude lookup is busy or its request cache is unavailable. Retrying on the next refresh."}


def poll_account_usage(claude_home: Path, token: str, expires_at: int, plan: str | None) -> dict[str, Any]:
    base = {"plan": plan, "limits": []}
    cache_path = usage_cache_path(claude_home)
    cache = read_cache(cache_path, token)
    saved = cache.get("account") if isinstance(cache.get("account"), dict) else {}
    now = time.time()
    if max(finite_number(cache.get("retryAt")) or 0, finite_number(cache.get("serverNotBefore")) or 0) > now:
        return {**base, **saved, "status": "error" if cache.get("message") or not saved else "ok", "message": cache.get("message") or ("" if saved else "Claude requested a cooldown before the next usage lookup.")}
    if (finite_number(cache.get("nextRequestAt")) or 0) > now or (saved and (finite_number(cache.get("fetchedAt")) or 0) > now - 300):
        return {**base, **saved} if saved else {**base, "status": "error", "message": "Claude usage lookup is cooling down."}
    # Reserve the interval before HTTP so an interrupted process cannot cause
    # the next widget instance to immediately repeat the request.
    if not write_cache(cache_path, {**cache, "nextRequestAt": now + 300}, token):
        return {**base, **saved, "status": "error", "message": "Cannot save Claude's request schedule; account lookup deferred."}
    error_code = None
    response_headers: dict[str, str] = {}
    server_not_before = now
    try:
        if expires_at and expires_at <= now * 1000:
            token = refresh_login(claude_home, token, response_headers)
            if header_retry_at(response_headers, time.time()) > time.time():
                raise ValueError("Claude requested a cooldown after refreshing credentials.")
        try:
            limits = fetch_limits(token, response_headers)
        except urllib.error.HTTPError as exc:
            if exc.code != 401 or header_retry_at(exc.headers, time.time()) > time.time():
                raise
            # A token can be revoked before its saved expiry. Retry once with
            # the newly refreshed (or concurrently updated) credentials.
            exc.close()
            token = refresh_login(claude_home, token, response_headers)
            if header_retry_at(response_headers, time.time()) > time.time():
                raise ValueError("Claude requested a cooldown after refreshing credentials.")
            limits = fetch_limits(token, response_headers)
        if not limits:
            raise ValueError("Claude returned no subscription usage windows.")
        result = {**base, "status": "ok", "message": "", "limits": limits}
        completed = time.time()
        server_not_before = header_retry_at(response_headers, completed)
        write_cache(cache_path, {"account": result, "fetchedAt": completed, "nextRequestAt": completed + 300, "serverNotBefore": server_not_before}, token)
        return result
    except urllib.error.HTTPError as exc:
        error_code = exc.code
        server_not_before = header_retry_at(exc.headers, time.time())
        message = ("Claude usage is rate limited (HTTP 429). Retrying after a cooldown." if exc.code == 429
                   else "Claude's login could not be refreshed. Run claude auth login." if exc.code in (400, 401, 403)
                   else f"Claude usage lookup returned HTTP {exc.code}.")
    except (OSError, ValueError) as exc:
        server_not_before = header_retry_at(response_headers, time.time())
        message = f"Claude limits unavailable: {exc}"
    latest_cache = read_cache(cache_path, token)
    if (finite_number(latest_cache.get("fetchedAt")) or 0) > (finite_number(cache.get("fetchedAt")) or 0):
        cache = latest_cache
        saved = cache.get("account") if isinstance(cache.get("account"), dict) else saved
    if saved:
        message += " Showing the last successful limits."
    completed = time.time()
    failures = integer(cache.get("failureCount")) + 1
    retry_at = max(completed + backoff_seconds(failures, 300 if error_code == 429 else 60), server_not_before)
    # Persist throttle waits independently of credentials; refreshing a token
    # is not permission to bypass an HTTP request-rate restriction.
    if error_code == 429:
        server_not_before = max(server_not_before, retry_at)
    write_cache(cache_path, {"account": saved, "fetchedAt": cache.get("fetchedAt", 0), "nextRequestAt": max(now + 300, retry_at), "retryAt": retry_at, "serverNotBefore": server_not_before, "failureCount": failures, "message": message}, token)
    return {**base, **saved, "status": "error", "message": message}


def collect(claude_home: Path, skip_remote: bool = False, history_days: int = 30) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "provider": {"id": "claude", "name": "Claude Code", "icon": "applications-development"},
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "account": account_usage(claude_home, skip_remote),
        "localActivity": scan_local_usage(claude_home, history_days),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-only", action="store_true", help="skip Claude subscription limit lookup")
    parser.add_argument("--history-days", type=int, default=30)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    claude_home = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    record = collect(claude_home, args.local_only, max(HISTORY_DAYS, args.history_days))
    json.dump(record, sys.stdout, indent=2 if args.pretty else None, separators=None if args.pretty else (",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
