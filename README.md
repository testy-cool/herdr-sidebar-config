# Herdr Sidebar Config

**See what each agent is doing, grouped by workspace and tab.**

A [Herdr](https://herdr.dev) sidebar preset: **workspace → tab → agent**, with
readable task labels and provider icons. Single-tab workspaces stay compact;
multiple tabs get a tree. Includes the configuration, icon font, and companion
plugin that keeps the rows current. No Herdr fork or font build required.

![Herdr Sidebar showing two tabs under herdr-sidebar and a compact icon-font workspace](docs/sidebar.png)

*Actual Herdr 0.8.2 rendering in Ghostty 1.3.1. Agent names, tasks, and states are
demonstration data in a separate session; the plugin and renderer are real.*

## Install

Requires **Herdr 0.8.2 or later**, **Python 3.11+**, and Git. The icon setup targets
Ghostty on Linux or macOS. Linux/Ghostty has been tested live; macOS paths are
provided but have not been tested in a live terminal.

Run inside a Herdr terminal pane:

```sh
git clone https://github.com/testy-cool/herdr-sidebar-config.git
cd herdr-sidebar-config
python3 setup_sidebar.py install
python3 setup_sidebar.py doctor
```

Open a **fresh Ghostty process** to load the newly installed font. Your Herdr
session keeps running; attach to it from that process. A new tab in an existing
Ghostty process may still use its old font cache.

Want to inspect the changes first? Run `python3 setup_sidebar.py install --dry-run`.
For another terminal, run `python3 setup_sidebar.py install --text` to use short
provider labels such as `AI` and `C`, with no font or Ghostty changes.

Setup links this checkout as a plugin, replaces the agent sidebar layout, sets
workspace sorting, and backs up modified files. It preserves other Herdr
settings. Keep the checkout where you installed it. See [setup details](docs/setup.md)
for custom paths, manual installation, and troubleshooting.

## What changes

- **One tab:** agents sit directly beneath their workspace name.
- **Multiple tabs:** each tab with agents gets a plain heading and compact tree.
  Tabs with no agent appear in a gray `terminals: explorer, backlog` row in the
  workspace's agent group. This is an informational row; switch tabs normally.
- **Inactive workspaces:** after ten minutes without any working agent, the
  workspace label and its agent group dim. Any agent starting work restores them.
- **Readable labels:** prefer native Codex/Claude conversation titles and Pi saved
  names. Latest instructions, terminal, tab, and agent names remain fallbacks.
  Conversation titles describe the task, not necessarily its latest individual
  action. No extra model call is involved.
- **Native state:** `◔` working, `?` blocked, `✓` completed, `○` idle, `·` unknown.
  Static by default; optional rotating loaders animate working agents only.
- **Optional activity order:** bring working workspace groups forward, followed
  by recent lifecycle activity. Tabs and agents keep their order within groups.
- **Provider icons:** Claude, Codex, OpenCode, OMP, Cline, Mastra Code, Kimi,
  Kilo, and Maki. Other agents get a diamond fallback.

The tree is a visual grouping; it does not add collapsible folders. Agent clicks
and keyboard navigation remain Herdr's native behavior. Long labels are clipped
to the sidebar width. Session history reads are local, bounded, and performed
only during existing refresh events.

The inactivity threshold defaults to 600 seconds. Set `inactive_after_seconds`
in the plugin config to change it. A single sleeping process per session handles
the next deadline and exits when no deadline or enabled animation remains. Ordinary focus changes do
not reset a quiet workspace's timer. On first installation, quiet periods start
when the plugin first observes each workspace.

## Settings

Press **`prefix+,`** or choose **Sidebar settings** in the command palette.
Setup adds the shortcut only when it is free. Arrow keys change ordering,
icons, dimming delay, **Animated loaders: Off / On**, and **Loader style**. Enter saves and applies;
Escape cancels. Preferences survive updates and removal.

Loaders default to **Off**. Choose **Dots** (rotating trail, default), **Orbit**
(single rotating dot), or **Pulse** (rising and falling dots). All use the same
single-cell braille grid at eight frames per second, replacing the uneven
quarter-circle animation. Off immediately restores `◔` and stops frame updates. No working agents
also stops animation. Enabling animation costs extra CPU; it does not change
agent status, run a model, or rescan transcripts per frame. See the
[earlier four-fps demo cost](docs/architecture.md#animation-cost).

## Refresh, update, or remove

Normal lifecycle events refresh the sidebar automatically. After manually
changing a title override or icon setting:

```sh
herdr plugin action invoke refresh --plugin testy-cool.herdr-sidebar
```

To update, run `git pull --ff-only` in this checkout, then repeat the install and
doctor commands. Setup refuses to overwrite files edited after installation;
use the [manual steps](docs/setup.md) when keeping later customizations.

To restore the files saved during setup:

```sh
python3 setup_sidebar.py uninstall --dry-run
python3 setup_sidebar.py uninstall
```

Removal clears generated tokens, disables the plugin, and restores its backups.
It keeps the checkout, plugin preferences, and disabled registration. If any managed layout/font file changed
since setup, removal stops before writing; [manual removal](docs/setup.md#manual-removal)
explains how to keep those edits.

## For agents and contributors

Start with [AGENTS.md](AGENTS.md). It contains the installation workflow, file
map, behavior contracts, and verification commands. All setup commands accept
`--json`; install and uninstall also accept `--dry-run`.

The runtime uses only Python's standard library. It reads a local Herdr snapshot,
reads matching native session names and a bounded history fallback, and publishes
changed display tokens. The default is event-driven, with no animation polling.
Opt-in loaders use the existing scheduler and direct local socket requests.
There is no telemetry, network service, or API key. [Architecture](docs/architecture.md) documents the data flow, token names,
icon settings, and development checks.

## Credits and license

Adapted from [moneycaringcoder/herdr-agent-icons](https://github.com/moneycaringcoder/herdr-agent-icons),
with a borderless Codex mark derived from
[qintmb/herdr-icon-agent-ui](https://github.com/qintmb/herdr-icon-agent-ui).

Code is [MIT licensed](LICENSE). Provider artwork keeps its original terms and
trademarks; see [third-party notices](assets/THIRD_PARTY_NOTICES.md). This is an
independent community plugin, not an official Herdr or provider product.
