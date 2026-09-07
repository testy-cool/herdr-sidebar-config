# Working with Herdr Sidebar Config

This repository packages a workspace → tab → agent sidebar preset for Herdr:
configuration, an icon font, and a companion plugin. The plugin publishes display
metadata to group existing agents. It does not launch agents, generate summaries,
or implement Herdr's renderer.

The repository is `testy-cool/herdr-sidebar-config`. The installed plugin ID stays
`testy-cool.herdr-sidebar` so existing configurations and metadata remain valid.

## Install for a user

Work within the user's requested scope. Run these from this checkout inside the
target Herdr session; `HERDR_ENV` must be `1`.

```sh
python3 setup_sidebar.py install --dry-run --json
python3 setup_sidebar.py install --json
python3 setup_sidebar.py doctor --json
```

For terminals other than Ghostty, add `--text` to both install commands. Setup
backs up modified files before writing. `--dry-run` reports paths and makes no
writes. JSON output has a `status` field; exit 0 means success, 1 means a setup
error or a doctor check needing attention, and 2 means invalid CLI arguments.

Inspect the rendered sidebar before claiming success. Doctor verifies the
configuration and hook, but cannot see which fonts a terminal process loaded.
If fonts were just installed, explain that a fresh Ghostty process is needed;
do not kill Ghostty or restart a live Herdr server on the user's behalf.

Removal: `python3 setup_sidebar.py uninstall --dry-run --json`, then the same
command without `--dry-run`. If files changed after setup, preserve those edits
and follow [manual removal](docs/setup.md#manual-removal).

## Repository map

| File | Responsibility |
| --- | --- |
| `herdr-plugin.toml` | Plugin identity, supported platforms, lifecycle hooks, actions |
| `sidebar.py` | Titles, grouping, tree prefixes, changed-token publishing |
| `activity_titles.py` | Exact-session native Codex, Claude and Pi names |
| `inactivity.py`, `deadline.py` | Quiet-period state and one sleeping deadline process |
| `runtime.py` | CLI calls, binary discovery, font/text selection |
| `sidebar-layout.toml` | Native Herdr rows and colors |
| `setup_sidebar.py`, `configuration.py` | Installation, backups, removal, checks |
| `tools/`, `assets/`, `font/`, `dist/` | Reproducible icon font and licensed source artwork |
| `tests/` | Grouping, config preservation, runtime and font contracts |

## Preserve these contracts

- Keep runtime dependency-free on Python 3.11+. `fontTools` is build/test only.
- Use native snapshot facts for agent identity and status. Never send prompts,
  keystrokes, stop commands, or synthetic agent states from the plugin runtime.
- Publish only changed `hs_*` display tokens under `plugin:testy-cool.herdr-sidebar`.
  Preserve the optional user-owned `hs_title` override and other plugins' tokens.
- Keep normal refresh event-driven; never add a `pane.updated` hook. The single
  deadline worker may animate cached working rows at 8 fps only when the user
  enables `animated_loaders` (off by default). No CLI, snapshot, title lookup,
  or transcript scan per frame. With animation off or no working agents, stop
  frame wakeups completely; retain only the existing quiet-period deadline.
  Frame writes and lifecycle refreshes share the group lock to prevent stale rows.
- Keep one workspace heading, and one heading per tab containing agents. Hide
  all tab headings/branches when the workspace has one actual tab. Shell-only
  tabs count toward this rule and are listed in the group's gray terminals row.
- Leave the workspace-to-tab connection plain; branches belong below tab names.
- Retain the braille blank used for indentation. Herdr trims normal whitespace
  from token values, and continuation rows have different native indentation.
- Preserve unrelated user settings and never commit local configs, backups,
  session captures, credentials, or personal paths.
- Keep upstream artwork licenses and attribution with any redistributed fonts.

## Verify changes

```sh
python3 -m unittest discover -s tests -v
python3 -m venv .venv-font
.venv-font/bin/pip install -r requirements-font.txt
.venv-font/bin/python -m unittest discover -s tests -v
```

After runtime/layout/setup changes, use a separate Herdr session **and a separate
config root** to test installation, refresh, a second-tab transition, doctor,
and removal. A named session alone still shares user configuration. Use demo
data for published captures and label it. Do not operate the user's working
agent panes to make a screenshot.

Read [architecture](docs/architecture.md) for the token contract and
[setup](docs/setup.md) for paths and troubleshooting. Check the installed Herdr
CLI help before changing commands; upstream documentation may describe a newer
release. Make small commits after relevant verification. Report what actually
ran, including any platform or live verification gaps.
