import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from collector.claude import parse_limits, scan_local_usage


class ClaudeLocalUsageTests(unittest.TestCase):
    def test_messages_are_deduplicated_and_cache_is_counted(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            project = home / "projects" / "example"
            project.mkdir(parents=True)
            path = project / "session.jsonl"
            first = self.event("message-1", "event-1", 2, 10, 20, 5)
            duplicate = self.event("message-1", "event-2", 2, 10, 20, 5)
            second = self.event("message-2", "event-3", 3, 7, 4, 6)
            path.write_text("\n".join(json.dumps(event) for event in (first, duplicate, second)))

            usage = scan_local_usage(home)

            totals = usage["totals"]
            self.assertEqual(totals["inputTokens"], 5)
            self.assertEqual(totals["cachedInputTokens"], 17)
            self.assertEqual(totals["cacheWriteInputTokens"], 24)
            self.assertEqual(totals["outputTokens"], 11)
            self.assertEqual(totals["totalTokens"], 57)
            self.assertEqual(totals["prompts"], 2)
            self.assertEqual(totals["sessions"], 1)

    @staticmethod
    def event(message_id, event_id, input_tokens, cache_read, cache_write, output_tokens):
        return {
            "type": "assistant",
            "uuid": event_id,
            "sessionId": "session-1",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": {
                "id": message_id,
                "role": "assistant",
                "model": "claude-test",
                "usage": {
                    "input_tokens": input_tokens,
                    "cache_read_input_tokens": cache_read,
                    "cache_creation_input_tokens": cache_write,
                    "output_tokens": output_tokens,
                },
            },
        }


class ClaudeLimitTests(unittest.TestCase):
    def test_usage_credits_are_reported_after_plan_windows(self):
        payload = {
            "five_hour": {"utilization": 0.4, "resets_at": "2026-09-02T14:39:59+00:00"},
            "seven_day": {"utilization": 0.1, "resets_at": "2026-09-08T06:59:59+00:00"},
            "limits": [],
            "spend": {
                "used": {"amount_minor": 250, "currency": "GBP", "exponent": 2},
                "limit": {"amount_minor": 1000, "currency": "GBP", "exponent": 2},
                "percent": 25,
                "enabled": True,
            },
        }

        limits = parse_limits(payload)

        self.assertEqual([limit["id"] for limit in limits], ["five_hour", "seven_day", "credits"])
        credits = limits[-1]
        self.assertEqual(credits["label"], "Credits")
        self.assertEqual(credits["usedPercent"], 25.0)
        self.assertEqual(credits["detail"], "\u00a32.50 of \u00a310.00")
        self.assertIsNone(credits["windowMinutes"])
        self.assertIsNone(credits["resetsAt"])

    def test_disabled_credits_are_omitted(self):
        payload = {"five_hour": {"utilization": 0.0}, "spend": {"enabled": False}, "extra_usage": {"is_enabled": True}}
        self.assertEqual([limit["id"] for limit in parse_limits(payload)], ["five_hour"])

    def test_extra_usage_block_is_a_fallback(self):
        payload = {"extra_usage": {"is_enabled": True, "monthly_limit": 1000, "used_credits": 0.0, "currency": "GBP", "decimal_places": 2}}
        credits = parse_limits(payload)[0]
        self.assertEqual(credits["detail"], "\u00a30.00 of \u00a310.00")
        self.assertEqual(credits["usedPercent"], 0.0)
