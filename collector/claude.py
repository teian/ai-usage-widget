#!/usr/bin/env python3
"""Collect Claude Code subscription limits and machine-local token activity."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
HISTORY_DAYS = 7
USAGE_ENDPOINT = "https://api.anthropic.com/api/oauth/usage"


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
    except (TypeError, ValueError):
        return 0


def local_date(value: Any, fallback_mtime: float) -> str:
    if isinstance(value, (int, float)):
        stamp = float(value) / 1000 if value > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(stamp).astimezone().date().isoformat()
    if value:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone().date().isoformat()
        except ValueError:
            pass
    return datetime.fromtimestamp(fallback_mtime).astimezone().date().isoformat()


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
    seen_messages: set[str] = set()
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
                    message = event.get("message") if isinstance(event.get("message"), dict) else {}
                    if event.get("type") != "assistant" and message.get("role") != "assistant":
                        continue
                    usage = message.get("usage") or event.get("usage")
                    if not isinstance(usage, dict):
                        continue
                    message_id = message.get("id") or event.get("messageId")
                    unique_id = str(message_id) if message_id else f"{path}:{event.get('uuid') or line_number}"
                    if unique_id in seen_messages:
                        continue
                    seen_messages.add(unique_id)
                    values = token_values(usage)
                    if values["totalTokens"] == 0:
                        continue
                    model = str(message.get("model") or event.get("model") or "claude")
                    session = str(event.get("sessionId") or path)
                    day = local_date(event.get("timestamp") or message.get("timestamp"), mtime)
                    if day not in daily:
                        continue
                    prompts += 1
                    sessions.add(session)
                    add_values(totals, values)
                    add_values(models[model], values)
                    daily[day]["tokens"] += values["totalTokens"]
                    daily[day]["prompts"] += 1
                    daily[day]["sessions"].add(session)
        except OSError:
            continue

    return {
        "scope": "machine",
        "historyDays": history_days,
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
        data = json.loads((claude_home / ".credentials.json").read_text(encoding="utf-8"))
        login = data.get("claudeAiOauth") or {}
    except (OSError, json.JSONDecodeError):
        return "", 0, None
    return (
        str(login.get("accessToken") or ""),
        integer(login.get("expiresAt")),
        plan_label(login.get("rateLimitTier"), login.get("subscriptionType")),
    )


def reset_time(value: Any) -> str | None:
    if value is None or value == "":
        return None
    text = str(value)
    if text.isdigit():
        stamp = int(text)
        stamp = stamp / 1000 if stamp > 10_000_000_000 else stamp
        return datetime.fromtimestamp(stamp, timezone.utc).isoformat()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return text


def used_percent(value: Any, percent_scaled: bool) -> float | None:
    try:
        number = float(str(value).strip().replace("%", ""))
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    return min(100.0, number if percent_scaled or number > 1 else number * 100)


def fetch_limits(access_token: str) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        USAGE_ENDPOINT,
        headers={
            "Authorization": f"Bearer {access_token}",
            "anthropic-beta": "oauth-2025-04-20",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
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
            decimals = int(used_block.get("exponent", limit_block.get("exponent", 2)))
            if used_block.get("amount_minor") is not None:
                used = int(used_block["amount_minor"]) / 10**decimals
            if limit_block.get("amount_minor") is not None:
                limit = int(limit_block["amount_minor"]) / 10**decimals
        except (TypeError, ValueError):
            used = limit = None
        currency = str(used_block.get("currency") or limit_block.get("currency") or "")
    if used is None and extra:
        try:
            decimals = int(extra.get("decimal_places", 2))
            used = float(extra.get("used_credits") or 0)
            limit = float(extra["monthly_limit"]) / 10**decimals if extra.get("monthly_limit") is not None else None
        except (TypeError, ValueError):
            used = None
        currency = str(extra.get("currency") or currency)
    if used is None:
        return None

    percent = used_percent((spend or {}).get("percent"), True)
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
    raw_values = [bucket.get("utilization") for bucket in (session, weekly) if bucket]
    scoped = payload.get("limits") if isinstance(payload.get("limits"), list) else []
    raw_values.extend(item.get("percent") for item in scoped if isinstance(item, dict))
    numeric = []
    for value in raw_values:
        try:
            numeric.append(float(str(value).replace("%", "")))
        except (TypeError, ValueError):
            pass
    percent_scaled = any(value >= 1 for value in numeric)
    limits: list[dict[str, Any]] = []
    for key, label, bucket in (("five_hour", "5-hour", session), ("seven_day", "Weekly", weekly)):
        if not bucket:
            continue
        percent = used_percent(bucket.get("utilization"), percent_scaled)
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
        percent = used_percent(item.get("percent"), percent_scaled)
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


def account_usage(claude_home: Path, skip_remote: bool) -> dict[str, Any]:
    token, expires_at, plan = oauth_login(claude_home)
    base = {"plan": plan, "limits": []}
    if skip_remote:
        return {**base, "status": "skipped", "message": "Account lookup skipped."}
    if not token:
        return {**base, "status": "unavailable", "message": "Sign in to Claude Code to see subscription limits."}
    if expires_at and expires_at <= time.time() * 1000:
        return {
            **base,
            "status": "unavailable",
            "message": "Claude Code's saved access token has expired. Start Claude Code to refresh it.",
        }
    try:
        return {**base, "status": "ok", "message": "", "limits": fetch_limits(token)}
    except urllib.error.HTTPError as exc:
        return {**base, "status": "error", "message": f"Claude usage endpoint returned HTTP {exc.code}."}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {**base, "status": "error", "message": f"Claude limits unavailable: {exc}"}


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
