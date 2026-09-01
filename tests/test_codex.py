import json
import tempfile
import unittest
from pathlib import Path

from collector.codex import scan_local_usage


class LocalUsageTests(unittest.TestCase):
    def test_cumulative_usage_is_differenced_and_duplicates_are_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            session_dir = home / "sessions" / "2026" / "09" / "01"
            session_dir.mkdir(parents=True)
            path = session_dir / "rollout.jsonl"
            events = [
                {"type": "turn_context", "payload": {"model": "gpt-test"}},
                self.token_event(100, 40, 10),
                self.token_event(250, 100, 30),
                self.token_event(250, 100, 30),
            ]
            path.write_text("\n".join(json.dumps(event) for event in events))

            usage = scan_local_usage(home)

            self.assertEqual(usage["totals"]["inputTokens"], 150)
            self.assertEqual(usage["totals"]["cachedInputTokens"], 100)
            self.assertEqual(usage["totals"]["outputTokens"], 30)
            self.assertEqual(usage["totals"]["totalTokens"], 280)
            self.assertEqual(usage["totals"]["prompts"], 2)
            self.assertEqual(usage["totals"]["sessions"], 1)
            self.assertEqual(usage["models"][0]["model"], "gpt-test")

    @staticmethod
    def token_event(input_tokens, cached_tokens, output_tokens):
        usage = {
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_tokens,
            "output_tokens": output_tokens,
        }
        return {
            "timestamp": "2026-09-01T12:00:00Z",
            "type": "event_msg",
            "payload": {"type": "token_count", "info": {"total_token_usage": usage}},
        }


if __name__ == "__main__":
    unittest.main()
