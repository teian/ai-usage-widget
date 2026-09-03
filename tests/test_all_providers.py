import unittest
from unittest.mock import patch

from collector.all_providers import collect


class ProviderSelectionTests(unittest.TestCase):
    @patch("collector.all_providers.collect_claude", return_value={"provider": {"id": "claude"}})
    @patch("collector.all_providers.collect_codex", return_value={"provider": {"id": "codex"}})
    @patch("collector.all_providers.resolve_codex", return_value="/usr/bin/codex")
    @patch("collector.all_providers.resolve_claude", return_value="/usr/bin/claude")
    def test_only_enabled_providers_are_collected(self, _resolve_claude, _resolve_codex, codex, claude):
        result = collect(skip_remote=True, enabled={"claude"})

        self.assertEqual([item["provider"]["id"] for item in result["providers"]], ["claude"])
        self.assertEqual(result["availableProviders"], {"codex": True, "claude": True})
        codex.assert_not_called()
        claude.assert_called_once()

    @patch("collector.all_providers.collect_claude")
    @patch("collector.all_providers.collect_codex")
    def test_an_explicit_empty_selection_collects_nothing(self, codex, claude):
        result = collect(skip_remote=True, enabled=set())

        self.assertEqual(result["providers"], [])
        codex.assert_not_called()
        claude.assert_not_called()

    @patch("collector.all_providers.collect_claude")
    @patch("collector.all_providers.collect_codex")
    @patch("collector.all_providers.resolve_codex", return_value=None)
    @patch("collector.all_providers.resolve_claude", return_value=None)
    def test_saved_provider_data_does_not_make_an_uninstalled_cli_visible(self, _resolve_claude, _resolve_codex, codex, claude):
        result = collect(skip_remote=True, enabled={"codex", "claude"})

        self.assertEqual(result["providers"], [])
        codex.assert_not_called()
        claude.assert_not_called()
