# AI Usage

A Plasma 6 widget for monitoring AI coding-agent usage. It shows subscription
allowances, reset times, local token activity, and model totals for Codex and
Claude Code.

Install **AI Usage** from the [KDE Store](https://store.kde.org/p/2370275/).

## Screenshots

<p>
  <img src="docs/codex-usage.png" alt="Codex usage view" width="320">
  <img src="docs/claude-usage.png" alt="Claude Code usage view" width="320">
</p>

## Features

- Codex subscription usage windows and reset times via `codex app-server`
- Claude Code subscription windows and usage-credit spend
- Seven-day local token activity with prompt and session counts
- Token totals grouped by model
- Separate provider gauges and configurable refresh interval

## Requirements

- KDE Plasma 6
- Python 3
- Codex CLI and/or Claude Code, installed and authenticated

The providers are optional: enable only the tools you use. The collector uses
only Python's standard library and uses the CLIs' existing credentials.

Local statistics are calculated from Codex session records under `CODEX_HOME`
(normally `~/.codex`) and Claude Code transcripts under `CLAUDE_CONFIG_DIR`
(normally `~/.claude`). They describe this machine, scoped to the same
seven-day window as the activity chart, while limits and account activity
come from each provider's service.

## Try the collector

```sh
./bin/ai-usage | python3 -m json.tool
```

The collectors use only the Python standard library. Codex authentication stays
inside `codex app-server`. The Claude collector reads the existing Claude Code
OAuth login to request subscription limits from Anthropic. Expired access
tokens are refreshed using the saved refresh token; rotated credentials are
written atomically back to Claude Code's credential file with owner-only
permissions, while cooperating with Claude Code's refresh locks. Tokens are
never printed or included in widget output. Local Claude statistics work
without account lookup.

Account lookups for both providers are cached for at least five minutes under
`$XDG_CACHE_HOME/ai-usage` (normally `~/.cache/ai-usage`). This minimum applies
to manual refreshes too; local token statistics still update on every refresh.
Concurrent widget instances share a request lock and schedule.

Claude HTTP responses are checked for `Retry-After` (seconds or an HTTP date)
and exhausted `anthropic-ratelimit-*-remaining` buckets with their reset times,
including successful responses and credential refreshes. The latest applicable
deadline wins and is never shortened by a configured refresh interval or a
token change. Failed requests use increasing backoff with jitter and retain the
last successful limits with a warning. Codex is accessed through its app-server
RPC interface, which does not expose upstream HTTP headers; the collector uses
the same minimum polling interval and failure backoff rather than interpreting
subscription reset times as HTTP request limits.

These rules follow [Anthropic's response-header guidance](https://platform.claude.com/docs/en/api/rate-limits#response-headers),
[OpenAI's rate-limit guidance](https://developers.openai.com/api/docs/guides/rate-limits),
and [HTTP Retry-After semantics](https://www.rfc-editor.org/rfc/rfc9110.html#field.retry-after).
The Claude OAuth usage endpoint has no published polling quota in those API
docs; the five-minute minimum is a conservative widget policy, not a claimed
provider limit. If a saved login can no longer be refreshed, run
`claude auth login` and refresh the widget. The cache contains usage information,
not credentials.

## Install for the current user

To install the latest local checkout instead, run:

```sh
./scripts/install.sh
```

This bundles `collector/` and the collector launcher into the plasmoid package
itself before installing it with `kpackagetool6`, so the widget is
self-contained - nothing is installed outside its own applet directory, and
`./scripts/uninstall.sh` removes it in one step.

Then add **AI Usage** from Plasma's widget picker. If it does not appear
immediately, restart the Plasma shell or log out and back in. On a
systemd-managed Plasma session, you can run:

```sh
systemctl --user restart plasma-plasmashell.service
```

The collector locates Codex from the desktop session `PATH` and common per-user
install locations. If Codex is installed somewhere unusual, set `CODEX_BIN` to
its absolute path before starting Plasma.

Right-click the widget and open **Configure AI Usage…** to enable or disable
Codex and Claude Code independently, or to change the refresh interval.

For development, run:

```sh
plasmawindowed com.github.d34ndev.aiusage
```

Uninstall with `./scripts/uninstall.sh`.

## Layout

```text
bin/ai-usage             bundled all-provider collector launcher
collector/               collection and normalization logic
plasmoid/package/        Plasma 6 package (install.sh bundles bin/ and collector/ into contents/)
schemas/                 provider record contract
tests/                    collector tests
```

Provider records are intentionally display-oriented JSON. A future provider
only needs to emit the same contract and place its record in the state
directory; it does not need to know anything about QML.
