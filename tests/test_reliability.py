import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from collector import claude, codex
from collector.all_providers import collect


class LocalRecoveryTests(unittest.TestCase):
    def test_codex_skips_non_object_and_malformed_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / "sessions").mkdir()
            events = [None, [], {"payload": []}, {"payload": {"type": "token_count", "info": []}},
                      {"timestamp": datetime.now(timezone.utc).isoformat(), "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 10, "output_tokens": 2}}}}]
            (home / "sessions/test.jsonl").write_text("{broken\n" + "\n".join(map(json.dumps, events)))
            self.assertEqual(codex.scan_local_usage(home)["totals"]["totalTokens"], 12)

    def test_claude_counts_updated_streaming_message_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / "projects").mkdir()
            def event(output, timestamp=None):
                return {"type": "assistant", "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
                        "message": {"id": "message-1", "usage": {"input_tokens": 3, "output_tokens": output}}}
            old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
            events = [[], None, event(20, old), event(0), event(8), event(8), event(2)]
            (home / "projects/test.jsonl").write_text("\n".join(map(json.dumps, events)))
            totals = claude.scan_local_usage(home)["totals"]
            self.assertEqual(totals["totalTokens"], 11)
            self.assertEqual(totals["prompts"], 1)

    def test_one_provider_failure_does_not_drop_the_other(self):
        with patch("collector.all_providers.resolve_codex", return_value="codex"), patch("collector.all_providers.resolve_claude", return_value="claude"), \
             patch("collector.all_providers.collect_codex", side_effect=OSError("failed")), \
             patch("collector.all_providers.collect_claude", return_value={"provider": {"id": "claude"}}):
            result = collect()
        self.assertEqual([p["provider"]["id"] for p in result["providers"]], ["codex", "claude"])
        self.assertEqual(result["providers"][0]["account"]["status"], "error")


class RpcRecoveryTests(unittest.TestCase):
    def run_server(self, script):
        proc = subprocess.Popen([sys.executable, "-u", "-c", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        def cleanup():
            proc.kill()
            proc.wait()
            reader = getattr(proc, "_rpc_reader", None)
            if reader:
                reader.thread.join(timeout=1)
            proc.stdin.close()
            proc.stdout.close()
        self.addCleanup(cleanup)
        return proc

    def test_notification_and_reply_in_one_write(self):
        proc = self.run_server('import sys,time\nsys.stdin.readline()\nsys.stdout.write(\'null\\n{"method":"notice"}\\n{"id":1,"result":{"ok":true}}\\n\')\nsys.stdout.flush()\ntime.sleep(2)')
        self.assertEqual(codex.rpc_request(proc, 1, "initialize", timeout=0.5), {"ok": True})

    def test_partial_line_respects_timeout(self):
        proc = self.run_server('import sys,time\nsys.stdin.readline()\nsys.stdout.write(\'{"id":1\')\nsys.stdout.flush()\ntime.sleep(2)')
        start = time.monotonic()
        with self.assertRaisesRegex(codex.RpcError, "timed out"):
            codex.rpc_request(proc, 1, "initialize", timeout=0.15)
        self.assertLess(time.monotonic() - start, 0.8)

    def test_eof_fails_immediately(self):
        proc = self.run_server('import sys\nsys.stdin.readline()')
        with self.assertRaisesRegex(codex.RpcError, "closed"):
            codex.rpc_request(proc, 1, "initialize", timeout=1)

    @patch("collector.codex.resolve_codex", return_value="missing-binary")
    def test_startup_failure_is_an_account_error(self, _resolve):
        with patch("collector.codex.subprocess.Popen", side_effect=FileNotFoundError("missing-binary")):
            self.assertEqual(codex.fetch_account_usage()["status"], "error")

    def test_stderr_flood_does_not_block_account_lookup(self):
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "codex"
            executable.write_text(f"#!{sys.executable}\n" + '''import json, sys
sys.stderr.write("diagnostic" * 20000)
sys.stderr.flush()
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request["method"]
    result = ({"account": {"type": "chatgpt"}} if method == "account/read" else
              {"rateLimits": {"primary": {"usedPercent": 12}}} if method == "account/rateLimits/read" else {})
    print(json.dumps({"id": request["id"], "result": result}), flush=True)
''')
            executable.chmod(0o755)
            with patch("collector.codex.resolve_codex", return_value=str(executable)):
                account = codex.fetch_account_usage()
            self.assertEqual(account["status"], "ok")
            self.assertEqual(account["limits"][0]["usedPercent"], 12)


class ClaudeAccountRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.cache_env = patch.dict(os.environ, {"XDG_CACHE_HOME": str(self.home / "cache")})
        self.cache_env.start()
        self.addCleanup(self.cache_env.stop)
        self.path = self.home / ".credentials.json"
        self.login = {"accessToken": "old-token", "refreshToken": "old-refresh", "expiresAt": int(time.time() * 1000) - 1, "subscriptionType": "max", "scopes": ["user:profile"]}
        self.path.write_text(json.dumps({"claudeAiOauth": self.login, "other": {"preserved": True}}))

    def test_expired_token_is_refreshed_atomically(self):
        response = {"access_token": "new-token", "refresh_token": "new-refresh", "expires_in": 3600}
        with patch("collector.claude.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(response).encode())) as request, \
             patch("collector.claude.fetch_limits", return_value=[{"id": "five_hour", "usedPercent": 1}]) as fetch:
            result = claude.account_usage(self.home, False)
        self.assertEqual(result["status"], "ok")
        fetch.assert_called_once_with("new-token", {})
        saved = json.loads(self.path.read_text())
        self.assertEqual(saved["claudeAiOauth"]["refreshToken"], "new-refresh")
        self.assertTrue(saved["other"]["preserved"])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(request.call_args.args[0].data)["refresh_token"], "old-refresh")

    def test_concurrent_credential_change_is_preserved(self):
        def response(*args, **kwargs):
            self.path.write_text(json.dumps({"claudeAiOauth": {**self.login, "accessToken": "cli-new-token"}}))
            return io.BytesIO(json.dumps({"access_token": "widget-token", "expires_in": 3600}).encode())
        with patch("collector.claude.urllib.request.urlopen", side_effect=response):
            token = claude.refresh_login(self.home, "old-token")
        self.assertEqual(token, "cli-new-token")
        self.assertEqual(json.loads(self.path.read_text())["claudeAiOauth"]["accessToken"], "cli-new-token")

    def test_401_refreshes_once_and_retries(self):
        self.path.write_text(json.dumps({"claudeAiOauth": {**self.login, "expiresAt": int(time.time() * 1000) + 3600000}}))
        error = urllib.error.HTTPError(claude.USAGE_ENDPOINT, 401, "unauthorized", {}, None)
        self.addCleanup(error.close)
        with patch("collector.claude.fetch_limits", side_effect=[error, [{"id": "five_hour"}]]) as fetch, \
             patch("collector.claude.refresh_login", return_value="new-token") as refresh:
            result = claude.account_usage(self.home, False)
        self.assertEqual(result["status"], "ok")
        refresh.assert_called_once_with(self.home, "old-token", {})
        self.assertEqual(fetch.call_count, 2)

    def test_429_keeps_last_limits_and_honors_cooldown(self):
        self.path.write_text(json.dumps({"claudeAiOauth": {**self.login, "expiresAt": int(time.time() * 1000) + 3600000}}))
        limits = [{"id": "five_hour", "usedPercent": 30}]
        cache = {"account": {"status": "ok", "message": "", "limits": limits}, "fetchedAt": time.time() - 600}
        claude.write_cache(claude.usage_cache_path(self.home), cache, "old-token")
        error = urllib.error.HTTPError(claude.USAGE_ENDPOINT, 429, "limited", {"Retry-After": "600"}, None)
        self.addCleanup(error.close)
        with patch("collector.claude.fetch_limits", side_effect=error) as fetch:
            first = claude.account_usage(self.home, False)
            second = claude.account_usage(self.home, False)
        self.assertEqual(first["limits"], limits)
        self.assertEqual(first, second)
        self.assertIn("last successful", first["message"])
        fetch.assert_called_once()

    def test_local_only_does_not_refresh_or_contact_service(self):
        with patch("collector.claude.refresh_login") as refresh, patch("collector.claude.fetch_limits") as fetch:
            result = claude.account_usage(self.home, True)
        self.assertEqual(result["status"], "skipped")
        refresh.assert_not_called()
        fetch.assert_not_called()

    def test_invalid_credentials_do_not_raise(self):
        self.path.write_text("[]")
        self.assertEqual(claude.account_usage(self.home, False)["status"], "unavailable")

    def test_stale_cli_lock_is_recovered(self):
        lock = self.home / ".oauth_refresh.lock"
        lock.mkdir()
        stale = time.time() - 120
        os.utime(lock, (stale, stale))
        with claude.credential_lock(self.home):
            self.assertTrue(lock.is_dir())
            self.assertGreater(lock.stat().st_mtime, stale)
        self.assertFalse(lock.exists())

    def test_live_cli_lock_is_not_removed(self):
        lock = self.home / ".oauth_refresh.lock"
        lock.mkdir()
        with patch("collector.claude.time.monotonic", side_effect=[0, 13]):
            with self.assertRaisesRegex(ValueError, "already in progress"):
                with claude.credential_lock(self.home):
                    self.fail("must not acquire the existing lock")
        self.assertTrue(lock.exists())

    def test_sub_one_percent_is_not_treated_as_a_fraction(self):
        limits = claude.parse_limits({"five_hour": {"utilization": 0.4}, "seven_day": {"utilization": 0.1}})
        self.assertEqual([limit["usedPercent"] for limit in limits], [0.4, 0.1])

    def test_legacy_extra_usage_amounts_share_minor_units(self):
        limits = claude.parse_limits({"extra_usage": {"is_enabled": True, "used_credits": 250, "monthly_limit": 1000, "currency": "GBP"}})
        self.assertEqual(limits[0]["detail"], "£2.50 of £10.00")
        self.assertEqual(limits[0]["usedPercent"], 25)


if __name__ == "__main__":
    unittest.main()
