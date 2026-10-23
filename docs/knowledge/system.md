# Current system view — 2026-09-15

Dated snapshot of what this repository is and does. Inspected at
`8974a146fe9eb3ec69234a0169795b184cb0cb05` with Herdr 0.8.2 and Python 3.12.3
locally; CI covers Python 3.11 and 3.13. Numbers here are mirrored in
[registry.json](registry.json), which the test suite checks against the code.

Herdr itself owns agent detection, lifecycle state, sidebar rendering and
navigation. This repository ships a layout preset, a token publisher that feeds
it, an icon font, and an installer. It never launches agents, sends prompts or
keystrokes, and never invents agent state.

## Components

| Module | Responsibility | Key symbols |
| --- | --- | --- |
| `sidebar.py` | Builds headings, tree prefixes, status rows and dim variants; publishes only changed tokens | `desired_rows`, `desired_headers`, `task_label`, `refresh`, `changed_tokens` |
| `activity_titles.py` | Exact-session native names for Codex (SQLite/index), Claude (title records) and Pi (`session_info`) | `activity_title`, `_codex`, `_claude`, `_pi` |
| `ipc.py` | One newline-delimited JSON request over the Herdr socket; 2 s timeout, 4 MiB cap | `call` |
| `deadline.py` | The single scheduler process: quiet-period deadlines plus optional animation frames; also spawns itself | `address`, `ensure_timer`, `run` |
| `inactivity.py` | Pure quiet-period state machine returning dimmed workspaces and the next deadline | `update_inactivity` |
| `animation.py` | Braille loader styles, frame cache, per-frame token patch | `STYLES`, `INTERVAL`, `glyph`, `cache_rows`, `publish_frame` |
| `ordering.py` | Whole-workspace activity ordering and the Herdr agent-view override | `order_groups`, `apply_view` |
| `preferences.py` | User-owned preferences: defaults, validation, comment-preserving patch, atomic save | `DEFAULTS`, `validate`, `patch`, `save` |
| `settings_ui.py` | Dependency-free curses popup; saves then refreshes synchronously | `FIELDS`, `open_popup`, `editor` |
| `runtime.py` | Herdr binary discovery, CLI wrapper, icon mode, provider logo maps | `PUA_LOGOS`, `TEXT_LOGOS`, `icon_mode`, `logo_for` |
| `configuration.py` | TOML surgery on the Herdr config: layout merge, Spaces dimming rows, settings shortcut, Ghostty mapping | `merge_layout`, `dimmable_spaces`, `settings_binding`, `ghostty_mapping` |
| `setup_sidebar.py` | `install` / `uninstall` / `doctor` with a backup record and change guard | `plan`, `install`, `uninstall`, `doctor`, `edited_files` |
| `run.sh` | Hook entry point: repairs `PATH`, `cd`s to the checkout, execs `python3 sidebar.py` | — |

Build tooling: `tools/build_font.py` generates the base font from
`font/codepoints.toml` and `assets/svg/`; `tools/build_sidebar_font.py` derives
the shipped font from it. Both are byte-deterministic; `tests/test_font.py` and
CI assert that the committed files match a fresh build.

## Data flow

```text
Herdr lifecycle event (14 hooks, no pane.updated)
  -> sh run.sh -> python3 sidebar.py
  -> group-headers.lock (exclusive)
  -> herdr api snapshot
  -> grouping, headings, title selection, quiet-period state
  -> diff desired vs currently reported tokens
  -> herdr pane/workspace report-metadata (changed keys only)
  -> Herdr renders sidebar-layout.toml
```

A refresh reads one snapshot and sends at most one metadata command per changed
pane and per workspace. One `deadline.py` worker per state directory sleeps on a
private datagram socket until the next quiet-period deadline or animation frame;
a queued `refresh` datagram or a timeout re-enters the same decision block. The
worker exits when there is neither a deadline nor a cached working row, and on
any API failure rather than retrying. Frame writes take the same group lock as
lifecycle refreshes, so a stale frame cannot repopulate a row a refresh cleared.

## Token contract

Publisher: `plugin:testy-cool.herdr-sidebar`. 23 tokens exist; 18 are consumed by
rows in the shipped layout, the rest by the agent-view sort, the Spaces fragment,
the user, or nothing at all.

| Token | Meaning | Consumed by |
| --- | --- | --- |
| `hs_group`, `hs_group_dim` | Workspace heading on its first agent | layout |
| `hs_tab`, `hs_tab_dim` | Tab heading on its first agent, when the workspace has more than one actual tab | layout |
| `hs_row_working`, `hs_row_blocked`, `hs_row_done`, `hs_row_idle`, `hs_row_unknown` | Status-first first line: exactly one holds indentation, branch, status mark and label (a named agent's icon, name and pane name) | layout |
| `hs_row_logo`, `hs_row_logo_dim` | Provider mark at the end of the first line | layout |
| `hs_row_logo_kimchi` | Replaces `hs_row_logo` on a bright Kimchi row, coloured `#FF521D` by the default rows | layout (default rows) |
| `hs_row_task`, `hs_row_task_dim` | A named agent's task line, starting under its icon | layout |
| `hs_logo`, `hs_logo_dim` | Indentation, branch and provider mark in the older logo-first layout | older layouts |
| `hs_logo_focus` | Retired focus-bar token, always cleared; selected rows keep the regular icon and prefix | nothing |
| `hs_gap` | Braille blank row after the last agent before another workspace | layout |
| `hs_terminals` | Names of terminal-only tabs in the workspace | layout |
| `hs_task`, `hs_task_dim` | Task line under a named agent in the older layout, indented under the name | older layouts |
| `hs_working`, `hs_blocked`, `hs_done`, `hs_idle`, `hs_unknown` | Older layout: exactly one populated with the native status mark and task label | older layouts |
| `hs_logo_kimchi` | Replaces `hs_logo` on a bright Kimchi row; Herdr rejects `rows_by_agent` for agents it does not know and caps a row at 16 tokens, so the default rows colour this one token `#FF521D` | older layouts |
| `hs_*_dim` | Mutually exclusive dim twins of group/tab/logo/status tokens | layout |
| `hs_workspace_rank` | Hidden 12-digit rank for the activity agent-view sort | view sort |
| `hs_space`, `hs_space_dim` | Workspace label in Spaces, bright or dim | Spaces fragment |
| `hs_title` | Optional user-owned title override; read, never written or cleared | user |
| `hs_parent` | Pane id of the agent that opened this pane, set by the opener; read, never written or cleared | user |

Rules that hold across the contract: absent generated values are cleared, a pane
that stops being an agent loses every generated key, `clear` removes this
plugin's values from the current session, and native identity plus other plugins'
metadata are never overwritten. `U+2800` (braille blank) preserves indentation
through Herdr's whitespace trimming; it is a spacer, not a loader. Status marks
are `◔ ? ✓ ○ ·`.

## Preferences

Seven user-owned keys, validated by `preferences.validate`, edited by the settings
popup, and read at refresh time. Documented gaps are recorded in
[evidence.md](evidence.md#contradictions), not silently fixed here.

| Key | Default | Allowed | Popup row |
| --- | --- | --- | --- |
| `order` | `workspace` | `workspace`, `activity` | Order |
| `icons` | `auto` | `auto`, `font`, `text` | Icons |
| `inactive_after_seconds` | `600` | positive finite number of seconds | Dim after (minutes) |
| `animated_loaders` | `false` | `false`, `true` | Animated loaders |
| `loader_style` | `dots` | `dots`, `orbit`, `pulse` | Loader style |
| `branch_length` | `standard` | `standard`, `short` | Branch length |
| `pane_names` | `false` | `false`, `true` | Pane name before task |

Preferences live in the plugin config directory's `config.toml` and survive
updates and removal; the installer writes only the `icons` key when it is absent.

## Provider marks

Thirteen provider marks ship in the private use area U+E1A0–U+E1AC, in a fixed order
that the font build enforces. Five of them get a per-provider color in the
shipped layout; every other mapped agent uses the neutral rows, and any unmapped
agent renders `◇`.

| Codepoint | Agent | Text label | Layout accent |
| --- | --- | --- | --- |
| U+E1A0 | claude | `C` | `#E68A67` |
| U+E1A1 | codex | `AI` | `#A78BFA` |
| U+E1A2 | opencode | `OC` | neutral |
| U+E1A3 | omp | `OMP` | neutral |
| U+E1A4 | cline | `CL` | neutral |
| U+E1A5 | mastracode | `MC` | neutral |
| U+E1A6 | kimi | `KIM` | neutral |
| U+E1A7 | kilo | `KIL` | neutral |
| U+E1A8 | maki | `MAK` | neutral |
| U+E1A9 | agy | `AGY` | `#6EA8FE` |
| U+E1AA | hermes | `HER` | `#F5A623` |
| U+E1AB | kimchi | `KCH` | `#FF521D` |
| U+E1AC | pi | `PI` | — |

Fonts: `dist/HerdrSidebarLogos-Regular.ttf` (family "Herdr Sidebar Logos", the
file setup installs; `claude`, `codex`, `agy`, `hermes`, `kimchi` and `pi` are redrawn larger) and
`dist/HerdrHarnessLogos-Regular.ttf` (family "Herdr Harness Logos", the build
intermediate). Hashes and glyph metrics are in [registry.json](registry.json).

## Surfaces

Herdr ships display tokens into an icon font, so the rendering styles available are limited. Colors: `#A8ADB9` neutral, `#F08080` blocked, `#91C788` done, plus the five provider accents above. Every dim variant is neutral gray with `dim = true`. The layout uses only `fg`, `dim`, `bold` — no background, italic or underline.

| Surface | Content |
| --- | --- |
| Hooks | 1 startup (`--restore-view`), 1 pane (`settings` popup), 3 actions (`settings`, `refresh`, `clear`), 14 events, deliberately no `pane.updated` |
| Setup CLI | `install` / `uninstall` / `doctor` with `--dry-run`, `--json`, `--text`, `--config`, `--ghostty-config`, `--font-dir`, `--state-dir`; exit 0 success, 1 error or doctor warning, 2 bad arguments; statuses `planned`, `installed`, `removed`, `ok`, `needs_attention`, `error` |
| Managed files | the Herdr layout, the plugin preferences file, the Ghostty config line `font-codepoint-map = U+E1A0-U+E1AC=Herdr Sidebar Logos`, and the installed font (the last two are skipped with `--text`) |
| Backup record | `<state dir>/install.json`: per-file `before` (base64 original or null), `installed_sha256`, optional `user_editable`; renamed to `uninstalled.json` after removal |
| Doctor checks | `plugin_enabled`, `layout_matches`, `workspace_dimming`, `workspace_sort`, `latest_hook_succeeded`, `preferences_valid`, `icon_mode_valid`, plus `font_installed` and `ghostty_mapping` in font mode |
| Runtime environment | `HERDR_PLUGIN_STATE_DIR`, `HERDR_PLUGIN_CONFIG_DIR`, `HERDR_PLUGIN_ID`, `HERDR_SOCKET_PATH`, `HERDR_BIN_PATH`, `HERDR_ENV`, `HERDR_CONFIG_PATH`, `XDG_CONFIG_HOME`, `CODEX_HOME`, `CLAUDE_CONFIG_DIR`, `PI_CODING_AGENT_DIR` |

## Verification surface

13 behaviour modules plus the knowledge check, 58 tracked tests, run by CI on
Ubuntu and macOS across Python 3.11 and 3.13 with the pinned fontTools, followed
by `git diff --exit-code -- dist/`. The suite covers grouping and headings, task
labels, native titles, inactivity, ordering, animation frames, icon modes,
preferences, configuration merging, fonts, branch length, pane names and the AGY
mark. It does not cover `refresh()`, `ipc.call`, `deadline.run`, the settings
popup, the workspace-level `hs_space` publish path, or focused rows — see
[evidence.md](evidence.md#unknowns).

Full commands and the isolated-session procedure are in
[runbooks.md](runbooks.md); the installer and drift details are also covered by
[../setup.md](../setup.md) and [../architecture.md](../architecture.md).
