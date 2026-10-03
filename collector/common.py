"""Small defensive helpers shared by the standalone collectors."""

import math
import fcntl
import hashlib
import json
import os
import random
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any


def finite_number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def local_date(value: Any, fallback_mtime: float) -> str:
    try:
        if isinstance(value, (int, float)):
            stamp = value / 1000 if value > 10_000_000_000 else value
            return datetime.fromtimestamp(stamp).astimezone().date().isoformat()
        if value:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone().date().isoformat()
    except (ValueError, OverflowError, OSError):
        pass
    return datetime.fromtimestamp(fallback_mtime).astimezone().date().isoformat()


def http_timestamp(value: str) -> float | None:
    try:
        stamp = parsedate_to_datetime(value)
        return stamp.replace(tzinfo=timezone.utc).timestamp() if stamp.tzinfo is None else stamp.timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def duration_seconds(value: str) -> float | None:
    """OpenAI reset headers use durations such as 6m0s, rather than dates."""
    parts = re.findall(r"(\d+(?:\.\d+)?)(ms|s|m|h|d)", value)
    if not parts or "".join(number + unit for number, unit in parts) != value:
        return None
    total = sum(float(number) * {"ms": .001, "s": 1, "m": 60, "h": 3600, "d": 86400}[unit] for number, unit in parts)
    return finite_number(total)


def header_retry_at(headers: Any, now: float) -> float:
    """Return the latest applicable HTTP retry/reset deadline, without a cap.

    Retry-After accepts seconds or an HTTP date (RFC 9110). RFC 3339 reset
    timestamps are used by Anthropic; OpenAI uses duration reset headers.
    A reset is only blocking when that bucket reports no requests/tokens left.
    """
    fields = {str(key).lower(): str(value).strip() for key, value in (headers or {}).items()}
    server_now = http_timestamp(fields.get("date", ""))
    reference = server_now if server_now is not None else now
    deadlines = [now]
    retry_after = fields.get("retry-after", "")
    delay = finite_number(retry_after)
    if delay is not None and delay >= 0:
        deadlines.append(now + delay)
    else:
        stamp = http_timestamp(retry_after)
        if stamp is not None:
            deadlines.append(now + max(0, stamp - reference))
    for key, remaining_raw in fields.items():
        if not key.startswith(("anthropic-ratelimit-", "x-ratelimit-remaining-")):
            continue
        if key.startswith("anthropic-ratelimit-") and key.endswith("-remaining"):
            reset_key = key.removesuffix("-remaining") + "-reset"
            is_duration = False
        elif key.startswith("x-ratelimit-remaining-"):
            reset_key = key.replace("-remaining-", "-reset-", 1)
            is_duration = True
        else:
            continue
        remaining = finite_number(remaining_raw)
        if remaining is None or remaining > 0:
            continue
        reset = fields.get(reset_key, "")
        if is_duration:
            seconds = duration_seconds(reset)
            if seconds is not None:
                deadlines.append(now + seconds)
        else:
            try:
                stamp = datetime.fromisoformat(reset.replace("Z", "+00:00"))
                if stamp.tzinfo is not None:
                    deadlines.append(now + max(0, stamp.timestamp() - reference))
            except (ValueError, OverflowError):
                pass
    return max(deadlines)


def backoff_seconds(failures: int, minimum: float = 60) -> float:
    # Cap only our fallback backoff, never a server-provided wait time.
    return min(3600, minimum * 2 ** min(max(0, failures - 1), 6)) + random.uniform(0, 5)


def account_cache_path(home: Path, provider: str) -> Path:
    identity = hashlib.sha256(str(home.resolve()).encode()).hexdigest()[:16]
    cache_home = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return cache_home / "ai-usage" / f"{provider}-{identity}.json"


def read_cache(path: Path, identity: str) -> dict[str, Any]:
    try:
        cache = json.loads(path.read_text())
        if isinstance(cache, dict):
            if cache.get("tokenHash") == hashlib.sha256(identity.encode()).hexdigest():
                return cache
            # Signing in again must not bypass a server-directed request ban.
            # Do not carry account statistics across different credentials.
            return {"serverNotBefore": cache.get("serverNotBefore", 0), "nextRequestAt": cache.get("nextRequestAt", 0)}
    except (OSError, ValueError):
        pass
    return {}


def write_cache(path: Path, cache: dict[str, Any], identity: str) -> bool:
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump({**cache, "tokenHash": hashlib.sha256(identity.encode()).hexdigest()}, handle, allow_nan=False)
        os.replace(temporary, path)
        return True
    except (OSError, ValueError):
        return False
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def cache_lock(path: Path):
    """Only one widget process may poll a provider at a time."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
