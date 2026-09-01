# AI Usage Widget

A Plasma 6 widget for keeping an eye on AI coding-agent allowances and token
activity. Codex and Claude Code are currently supported; providers are
deliberately isolated so others can be added without changing the widget.

## What the prototype shows

- Codex subscription usage windows and reset times via `codex app-server`
- Claude Code subscription windows via its best-effort OAuth usage endpoint
- Seven-day local token activity as a bar chart, with prompt and session counts
- Token totals grouped by model
- Account-level token activity when Codex makes it available

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
OAuth token solely to request subscription limits from Anthropic; it never
prints or stores that token. Local Claude statistics work without that request.

## Install for the current user

```sh
./scripts/install.sh
```

Then add **AI Usage** from Plasma's widget picker. Refresh Plasma if it does not
appear immediately:

```sh
kquitapp6 plasmashell && kstart plasmashell
```

Right-click the widget and open **Configure AI Usage…** to enable or disable
Codex and Claude Code independently, or to change the refresh interval.

For development, run:

```sh
plasmawindowed com.github.dean.aiusage
```

Uninstall with `./scripts/uninstall.sh`.

## Layout

```text
bin/ai-usage             all-provider collector
bin/ai-usage-{provider}  individual provider collectors
collector/               collection and normalization logic
plasmoid/package/        Plasma 6 package
schemas/                 provider record contract
tests/                    collector tests
```

Provider records are intentionally display-oriented JSON. A future provider
only needs to emit the same contract and place its record in the state
directory; it does not need to know anything about QML.
