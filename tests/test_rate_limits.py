import io
import json
import os
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from email.utils import formatdate
from pathlib import Path
from unittest.mock import patch

from collector import claude, codex
from collector.common import account_cache_path, cache_lock, header_retry_at, read_cache, write_cache


class HeaderTests(unittest.TestCase):
    now = 1710000000

    def test_retry_after_accepts_seconds_and_http_dates(self):
        self.assertEqual(header_retry_at({"retry-after": "600"}, self.now), self.now + 600)
        self.assertEqual(header_retry_at({"Retry-After": formatdate(self.now + 900, usegmt=True)}, self.now), self.now + 900)

    def test_server_date_accounts_for_clock_skew(self):
        server_now = self.now - 120
        headers = {"Date": formatdate(server_now, usegmt=True), "Retry-After": formatdate(server_now + 600, usegmt=True)}
        self.assertEqual(header_retry_at(headers, self.now), self.now + 600)

    def test_long_server_wait_is_never_capped(self):
        self.assertEqual(header_retry_at({"Retry-After": "86400"}, self.now), self.now + 86400)

    def test_latest_exhausted_bucket_and_retry_after_win(self):
        stamp = lambda offset: datetime.fromtimestamp(self.now + offset, timezone.utc).isoformat()
        headers = {"retry-after": "100", "anthropic-ratelimit-requests-remaining": "0", "anthropic-ratelimit-requests-reset": stamp(200),
                   "anthropic-ratelimit-tokens-remaining": "0", "anthropic-ratelimit-tokens-reset": stamp(900)}
        self.assertEqual(header_retry_at(headers, self.now), self.now + 900)

    def test_nonempty_buckets_do_not_block_polling(self):
        headers = {"anthropic-ratelimit-requests-remaining": "1", "anthropic-ratelimit-requests-reset": "2099-01-01T00:00:00Z"}
        self.assertEqual(header_retry_at(headers, self.now), self.now)

    def test_openai_duration_reset_headers(self):
        headers = {"x-ratelimit-remaining-requests": "0", "x-ratelimit-reset-requests": "6m0s",
                   "x-ratelimit-remaining-tokens": "0", "x-ratelimit-reset-tokens": "1h2m3.5s"}
        self.assertEqual(header_retry_at(headers, self.now), self.now + 3723.5)

    def test_invalid_or_past_headers_do_not_create_a_wait(self):
        for value in ("NaN", "inf", "-1", "bogus", formatdate(self.now - 600, usegmt=True)):
            with self.subTest(value=value):
                self.assertEqual(header_retry_at({"Retry-After": value}, self.now), self.now)


class PollingTests(unittest.TestCase):
    now = 1710000000

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        env = patch.dict(os.environ, {"XDG_CACHE_HOME": str(self.home / "cache")})
        env.start()
        self.addCleanup(env.stop)
        clock = patch("collector.claude.time.time", return_value=self.now)
        clock.start()
        self.addCleanup(clock.stop)
        jitter = patch("collector.common.random.uniform", return_value=0)
        jitter.start()
        self.addCleanup(jitter.stop)
        self.token = "test-access-token"
        self.login = {"accessToken": self.token, "refreshToken": "test-refresh-token", "expiresAt": (self.now + 3600) * 1000}
        (self.home / ".credentials.json").write_text(json.dumps({"claudeAiOauth": self.login}))
        self.path = claude.usage_cache_path(self.home)

    def error(self, status, headers):
        error = urllib.error.HTTPError(claude.USAGE_ENDPOINT, status, "test error", headers, None)
        self.addCleanup(error.close)
        return error

    def test_503_http_date_is_respected_without_early_retry(self):
        headers = {"Retry-After": formatdate(self.now + 7200, usegmt=True)}
        with patch("collector.claude.fetch_limits", side_effect=self.error(503, headers)) as fetch:
            first = claude.account_usage(self.home, False)
            second = claude.account_usage(self.home, False)
        self.assertEqual(first, second)
        self.assertEqual(read_cache(self.path, self.token)["retryAt"], self.now + 7200)
        fetch.assert_called_once()

    def test_200_exhausted_quota_defers_future_requests(self):
        response = io.BytesIO(json.dumps({"five_hour": {"utilization": 20}}).encode())
        response.headers = {"anthropic-ratelimit-requests-remaining": "0", "anthropic-ratelimit-requests-reset": datetime.fromtimestamp(self.now + 3600, timezone.utc).isoformat()}
        with patch("collector.claude.urllib.request.urlopen", return_value=response) as request:
            first = claude.account_usage(self.home, False)
            with patch("collector.claude.time.time", return_value=self.now + 600):
                second = claude.account_usage(self.home, False)
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "ok")
        request.assert_called_once()

    def test_401_with_retry_after_does_not_refresh_or_retry(self):
        with patch("collector.claude.fetch_limits", side_effect=self.error(401, {"Retry-After": "600"})) as fetch, patch("collector.claude.refresh_login") as refresh:
            claude.account_usage(self.home, False)
        refresh.assert_not_called()
        fetch.assert_called_once()
        self.assertEqual(read_cache(self.path, self.token)["serverNotBefore"], self.now + 600)

    def test_credential_refresh_success_headers_also_defer_lookup(self):
        self.login["expiresAt"] = (self.now - 1) * 1000
        (self.home / ".credentials.json").write_text(json.dumps({"claudeAiOauth": self.login}))
        response = io.BytesIO(json.dumps({"access_token": "new-token", "expires_in": 3600}).encode())
        response.headers = {"Retry-After": "600"}
        with patch("collector.claude.urllib.request.urlopen", return_value=response) as request, patch("collector.claude.fetch_limits") as fetch:
            result = claude.account_usage(self.home, False)
        request.assert_called_once()
        fetch.assert_not_called()
        self.assertEqual(result["status"], "error")
        self.assertEqual(read_cache(self.path, "new-token")["serverNotBefore"], self.now + 600)

    def test_token_change_does_not_bypass_throttle(self):
        with patch("collector.claude.fetch_limits", side_effect=self.error(429, {"Retry-After": "600"})):
            claude.account_usage(self.home, False)
        (self.home / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {**self.login, "accessToken": "another-token"}}))
        with patch("collector.claude.fetch_limits") as fetch:
            result = claude.account_usage(self.home, False)
        fetch.assert_not_called()
        self.assertEqual(result["limits"], [])
        self.assertEqual(result["status"], "error")

    def test_concurrent_widget_does_not_issue_duplicate_request(self):
        with cache_lock(self.path), patch("collector.claude.fetch_limits") as fetch:
            result = claude.account_usage(self.home, False)
        fetch.assert_not_called()
        self.assertEqual(result["status"], "error")

    def test_interrupted_request_reservation_blocks_next_process(self):
        write_cache(self.path, {"nextRequestAt": self.now + 300}, self.token)
        with patch("collector.claude.fetch_limits") as fetch:
            claude.account_usage(self.home, False)
        fetch.assert_not_called()

    def test_repeated_429_without_headers_increases_backoff(self):
        with patch("collector.claude.fetch_limits", side_effect=self.error(429, {})) as fetch:
            claude.account_usage(self.home, False)
            self.assertEqual(read_cache(self.path, self.token)["retryAt"], self.now + 300)
            with patch("collector.claude.time.time", return_value=self.now + 301):
                claude.account_usage(self.home, False)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(read_cache(self.path, self.token)["retryAt"], self.now + 301 + 600)

    def test_codex_reuses_account_lookup_for_five_minutes(self):
        result = {"status": "ok", "message": "", "limits": [{"usedPercent": 100}]}
        with patch("collector.codex.fetch_account_usage", return_value=result) as fetch:
            self.assertEqual(codex.cached_account_usage(self.home), result)
            self.assertEqual(codex.cached_account_usage(self.home), result)
        fetch.assert_called_once()

    def test_codex_token_rotation_does_not_issue_another_lookup(self):
        auth = {"auth_mode": "chatgpt", "tokens": {"account_id": "account-1", "access_token": "old"}, "last_refresh": "earlier"}
        path = self.home / "auth.json"
        path.write_text(json.dumps(auth))
        result = {"status": "ok", "message": "", "limits": [{"usedPercent": 10}]}
        def fetch_and_rotate():
            path.write_text(json.dumps({**auth, "tokens": {**auth["tokens"], "access_token": "rotated"}, "last_refresh": "now"}))
            return result
        with patch("collector.codex.fetch_account_usage", side_effect=fetch_and_rotate) as fetch:
            self.assertEqual(codex.cached_account_usage(self.home), result)
            self.assertEqual(codex.cached_account_usage(self.home), result)
        fetch.assert_called_once()

    def test_codex_failure_keeps_limits_and_backs_off(self):
        result = {"status": "ok", "message": "", "limits": [{"usedPercent": 10}]}
        with patch("collector.codex.fetch_account_usage", return_value=result):
            codex.cached_account_usage(self.home)
        with patch("collector.codex.time.time", return_value=self.now + 301), patch("collector.codex.fetch_account_usage", return_value={"status": "error", "message": "RPC unavailable", "limits": []}) as fetch:
            first = codex.cached_account_usage(self.home)
            second = codex.cached_account_usage(self.home)
        self.assertEqual(first, second)
        self.assertEqual(first["limits"], result["limits"])
        fetch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
