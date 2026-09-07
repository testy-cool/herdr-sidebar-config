# How it works

Herdr owns agent detection, lifecycle state, sidebar rendering, and navigation.
This plugin turns those existing facts into display tokens. The layout file
decides how Herdr draws them; the bundled font supplies provider marks.

```text
Herdr lifecycle event
  -> run.sh -> sidebar.py
  -> herdr api snapshot
  -> workspace/tab grouping and task-title selection
  -> compare desired tokens with current tokens
  -> herdr pane report-metadata (changed panes only)
  -> Herdr renders sidebar-layout.toml
```

Each hook is a short Python process. A file lock serializes overlapping hooks.
One deadline process sleeps on a local socket until the next quiet-period
deadline. Animation is off by default. A refresh reads one
snapshot and sends at most one metadata command per changed pane. The CLI calls
have timeouts. Frequent lifecycle events can still start many hooks; this is not
a claim of zero overhead or a measured benchmark.

## Grouping and titles

Snapshot order follows Herdr's workspace/tab/pane order. The layout requires
workspace sorting (`agent_panel_sort = "spaces"`) as its default. Optional
activity ordering ranks whole workspaces by working status, then the latest
native lifecycle-change sequence; ties retain native order. A hidden
`hs_workspace_rank` token and `agent.view.set` apply this same order to Herdr's
view. Tabs and panes retain native order, and headings are generated from the
ordered rows. The view is restored at startup and cleared by owner when returning
to workspace order or removing the plugin. It does not filter agents or move
actual workspaces. A workspace header lives on its first agent; a tab header lives on its
first agent within a workspace with more than one actual tab. Shell-only tabs
count toward tab identity and appear in a gray `hs_terminals` line on the group's
first agent. They remain terminals; no fake agent identity is reported. A
workspace with no detected agents at all has no anchor in Herdr's Agents panel
and remains visible in Spaces.

The outer workspace-to-tab connection has no branch. Under each tab, agents use
`├─` and `└─`. A workspace with one tab has neither tab headings nor branches.
The tree is presentational, with native Herdr row selection and navigation.

Titles prefer a user `hs_title` token, then a native exact-session name from
Codex's read-only SQLite/index, Claude's name/title records, or Pi's saved
session_info. Project-only and trivial names are rejected. For a working Codex or Claude pane with a
native session ID, the plugin scans at most the final 512 KiB of that provider's
local history and selects its latest meaningful user instruction. Malformed
records, injected instruction headers, screenshot markers, and vague follow-ups
are skipped. Other cases use the existing terminal title, then tab, pane, and
provider fallbacks. These are deterministic local heuristics, not conversation
analysis or a model call.

## Token contract

Publisher: `plugin:testy-cool.herdr-sidebar`.

| Token | Meaning |
| --- | --- |
| `hs_group` | Workspace heading on its first agent |
| `hs_tab` | Tab heading on its first agent, when multiple tabs exist |
| `hs_logo` | Indentation, optional branch, and provider icon/text |
| `hs_working`, `hs_blocked`, `hs_done`, `hs_idle`, `hs_unknown` | Exactly one populated with the native status symbol and task label |
| `hs_gap` | Blank row after the last agent before another workspace |
| `hs_terminals` | Names of terminal-only tabs in this workspace |
| `hs_*_dim` | Mutually exclusive dim versions of agent/group display tokens |
| `hs_space`, `hs_space_dim` | Mutually exclusive workspace labels in Spaces |
| `hs_title` | Optional user-owned title override; read but never written or cleared by this plugin |

Absent generated values are cleared, including when a pane stops being an
agent. Native identity/state and other plugins' metadata are not overwritten.
`clear` removes generated values from the current session. Run it before
disabling the plugin; future lifecycle events can repopulate them while enabled.

U+2800, a blank braille cell, preserves indentation through metadata whitespace
trimming. It is a spacer, not a loader. Herdr's first and continuation rows have
different native offsets, so the prefix arithmetic is intentional.

`inactivity.py` preserves a quiet start per workspace. Any working agent clears
it; focus and title changes do not. At 600 seconds, refresh switches the label,
heading, tab and agent tokens to their dim variants. Native lifecycle symbols
in Spaces retain their meaning. `deadline.py` holds a single process lock and
waits on a private Unix datagram socket until the earliest deadline. Refreshes
reschedule that wait; no deadlines means exit. Removal clears both pane and
workspace tokens and cancels the pending wait.

## Optional loaders

`animated_loaders = true` lets the same scheduler update cached working rows
at eight frames per second. `loader_style` selects dots (default), orbit or pulse;
all frames use one braille cell instead of the old mixed quarter-circle glyphs.
Lifecycle refreshes cache the working pane IDs, loader style,
provider identity, selected token and task text under the shared group lock.
Frame writes take that same lock and reread the cache, so a completed/closed
pane cleared by a refresh cannot be repopulated by a stale frame.

Frames use direct socket requests: one narrow plugin-registry lookup to stop
when disabled, then one working-token patch per cached working pane. No CLI
process, snapshot, title computation or transcript scan runs per frame. API
failure ends the worker rather than retrying in a busy loop. The next lifecycle
refresh can restart it. Turning animation off immediately publishes `◔` and
empties the cache; no working rows means no frame deadlines. Quiet-workspace
deadlines remain independent.

### Animation cost

An isolated Linux Herdr 0.8.2 demo with two workspaces, one working agent and a
140×40 terminal client was sampled for eight seconds per mode on 2026-09-08.
This is the historical four-fps animation baseline, not a measurement of the
current eight-fps styles. Percentages below are of one CPU core, not the whole machine:

| Process | Animation on | Animation off |
| --- | ---: | ---: |
| Herdr server | 2.00% | 0.25% |
| Herdr client | 0.625% | 0.00% |
| Shared scheduler | 0.25% | 0.00% |

The scheduler used about 10.2 MiB PSS in both modes because a dimming deadline
was pending. The disabled client produced no new rendering bytes during the
observation. These short, one-agent measurements are not a many-agent benchmark;
cost increases with working rows and depends on the terminal and machine.

## Icon configuration

Set `icons` in the plugin config directory's `config.toml`:

| Value | Behavior |
| --- | --- |
| `"font"` | Use the bundled U+E1A0–U+E1A8 marks; setup's Ghostty default |
| `"text"` | Use short labels; selected by setup's `--text` |
| `"auto"` | Default without setup: use font mode if `fc-match` finds the exact family, otherwise text |

Font discovery does not prove the terminal has loaded the font. macOS without
Fontconfig will use text in auto mode; setup selects explicit font mode. The
Claude and Codex outlines extend beyond one nominal cell and use the following
space in Ghostty, which makes their size readable without shrinking the text.

## Development

Run `python3 -m unittest discover -s tests -v` for dependency-free checks. Font
tests skip when the optional build dependency is unavailable. For all checks:

```sh
python3 -m venv .venv-font
.venv-font/bin/pip install -r requirements-font.txt
.venv-font/bin/python -m unittest discover -s tests -v
```

Rebuild fonts with `.venv-font/bin/python tools/build_font.py`, then
`.venv-font/bin/python tools/build_sidebar_font.py`. Commit the source changes
and matching `dist/` files. Tests compare rebuilt fonts byte for byte. Preserve
the artwork provenance in [third-party notices](../assets/THIRD_PARTY_NOTICES.md).

Live verification uses Herdr 0.8.2 and Ghostty 1.3.1 on Linux. The README capture
comes from an isolated session with four demonstration agent reports. Installation,
repeat installation, doctor, font rendering, and restoration of the original
files were exercised there. Unit tests also cover single/multiple-tab transitions,
unchanged metadata, unrelated settings, and refusal to overwrite later edits.
macOS terminal rendering remains unverified.
