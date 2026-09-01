import json
import tempfile
import unittest
from pathlib import Path

from collector.claude import scan_local_usage


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
            "timestamp": "2026-09-01T12:00:00Z",
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
