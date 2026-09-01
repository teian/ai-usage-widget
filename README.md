# AI Usage Widget

A Plasma 6 widget for keeping an eye on AI coding-agent allowances and token
activity. The first provider is Codex; providers are deliberately isolated so
Claude and others can be added without changing the widget.

## What the prototype shows

- Codex subscription usage windows and reset times via `codex app-server`
- Local input, cached-input, output, prompt, and session counts
- Seven-day token activity
- Token totals grouped by model
- Account-level token activity when Codex makes it available

Local statistics are calculated from Codex session records under `CODEX_HOME`
(normally `~/.codex`). They describe this machine, while limits and account
activity come from Codex services.

## Try the collector

```sh
./bin/ai-usage-codex | python3 -m json.tool
```

The collector uses only the Python standard library. It does not read or copy
credentials; `codex app-server` uses the existing Codex login.

## Install for the current user

```sh
./scripts/install.sh
```

Then add **AI Usage** from Plasma's widget picker. Refresh Plasma if it does not
appear immediately:

```sh
kquitapp6 plasmashell && kstart plasmashell
```

For development, run:

```sh
plasmawindowed com.github.dean.aiusage
```

Uninstall with `./scripts/uninstall.sh`.

## Layout

```text
bin/ai-usage-codex       executable collector
collector/               collection and normalization logic
plasmoid/package/        Plasma 6 package
schemas/                 provider record contract
tests/                    collector tests
```

Provider records are intentionally display-oriented JSON. A future provider
only needs to emit the same contract and place its record in the state
directory; it does not need to know anything about QML.
