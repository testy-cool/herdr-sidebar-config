# Setup and troubleshooting

Use the [README quick start](../README.md#install) for the supported installation
flow. Run setup from the same checkout and Herdr session each time.

## Files setup manages

Open **Sidebar settings** from the command palette or press `prefix+,` (setup
adds this shortcut only when unclaimed). Arrow keys change ordering, icons, loaders and the dimming
delay; type a number on the minutes row for an exact delay. Enter saves and
applies once; Escape cancels. You can also open it with:

```sh
herdr plugin action invoke settings --plugin testy-cool.herdr-sidebar
```

On Windows, Herdr needs distinct action ids per platform, so every action in
this guide ends in `-windows`: `settings-windows`, `refresh-windows`, and
`clear-windows`.

Plugin preferences are user-owned. Updates retain them, `--text` explicitly
selects text icons, and uninstall leaves preferences available for a later
reinstall. Older setup backups are migrated without losing their original bytes.

**Branch length** controls the tree under tabs: **Standard** uses `├─` / `└─`,
and **Short** uses `├` / `└`, saving one column without removing indentation.
The config key is `branch_length = "standard"` (default) or `"short"`.
Single-tab workspaces stay branch-free with either choice.

Ordering defaults to `order = "workspace"`. Choose `"activity"` to bring working
workspace groups forward, followed by recent lifecycle activity. Tabs and agents
stay together in their original order; Spaces is unchanged. The activity view
owns Herdr's single agent-view override, so do not combine it with another
plugin's agent filter/sort. Switching back clears only this plugin's override.

`animated_loaders = false` is the default. Enabling it animates working agents
at eight frames per second. Set **Loader style** to **Dots**, **Orbit**, or
**Pulse** (`loader_style = "dots"`, `"orbit"`, or `"pulse"`); Dots is the default.
Changing style does not turn animation on. Switching animation off restores the static indicator and
stops frame wakeups; ordinary inactivity dimming continues. The popup applies
these preferences immediately without restarting Herdr or agent processes.

| Item | Default location |
| --- | --- |
| Herdr layout | `$XDG_CONFIG_HOME/herdr/config.toml`, or `~/.config/herdr/config.toml` |
| Plugin icon setting | The directory printed by `herdr plugin config-dir testy-cool.herdr-sidebar`, then `config.toml` |
| Linux font | `~/.local/share/fonts/HerdrSidebarLogos-Regular.ttf` |
| macOS font | `~/Library/Fonts/HerdrSidebarLogos-Regular.ttf` |
| Linux Ghostty config | `$XDG_CONFIG_HOME/ghostty/config`, or `~/.config/ghostty/config` |
| macOS Ghostty config | `~/Library/Application Support/com.mitchellh.ghostty/config` |
| Windows Herdr layout | `%APPDATA%\herdr\config.toml` |
| Windows font | `%LOCALAPPDATA%\Microsoft\Windows\Fonts\HerdrSidebarLogos-Regular.ttf`, registered under `HKCU\Software\Microsoft\Windows NT\CurrentVersion\Fonts` |
| Windows hook interpreter | `python-path.txt` in the plugin config directory |
| Backups | `herdr-sidebar-setup/install.json` beside the Herdr config |

`HERDR_CONFIG_PATH` selects a non-default Herdr config. It must be the config of
the running session. `--config` may name that same path, but cannot retarget an
already-running server. `--ghostty-config`, `--font-dir`, and `--state-dir` accept
explicit paths; repeat custom path flags for doctor and uninstall.

The installer edits `[ui.sidebar.agents]` and its child tables, replaces only the
workspace-name token in Spaces with bright/dim alternatives, and sets
`[ui].agent_panel_sort = "spaces"`. Other parsed settings must remain equal or
setup refuses the edit. Ordinary tables and array tables are supported; unusual
inline/dotted table forms may require manual installation. A matching existing
layout is left alone.

Backups contain original file bytes, including any private values already in
your config. They are local files written with restrictive permissions; never
publish them. Repeated installs retain the first backup. Later edits to the Herdr
config, such as a new theme, are kept: setup merges the layout into the current
file again, and removal restores only the sidebar tables, `agent_panel_sort`, and
the settings shortcut from the backup (the whole original file when nothing else
changed). Setup and removal stop if another managed file (font, interpreter
record, Ghostty config) has since changed; editable plugin preferences are
excluded from that guard and from restoration. An interrupted setup retains its backup for
inspection and recovery. The helper is intended for one active session at a
time; other running sessions that share the config may need their own refresh.

## Windows

Setup records the absolute path of the Python that ran it in `python-path.txt`
(one UTF-8 line) in the plugin config directory. The hook launcher `run.cmd`
uses it, then falls back to `py -3` and `python`. Herdr resolves hook commands
itself and skips `.bat` shims such as pyenv-win's, so the record keeps hooks on
the interpreter you chose. Run setup again with another Python to change it.
The record is a managed file: uninstall removes it and refuses if it was edited.

In font mode, setup copies the font to your user font directory and registers it
for your user; no administrator rights are needed. Uninstall removes both, and
restores an earlier registration of the same name if one existed. Windows'
font cache keeps a registered font file open, so setup releases the registration
before replacing or removing the file.

Setup never edits Windows Terminal's `settings.json`. Add the fallback yourself:
in Settings → Profile (or Defaults) → Appearance → **Font face**, append
`, Herdr Sidebar Logos` after your current font, for example
`Cascadia Mono, Herdr Sidebar Logos`. Windows Terminal 1.21 or later reads the
comma-separated list as fallbacks. Open a new Windows Terminal window afterward.
Doctor reads the stable, Preview, and unpackaged `settings.json` and reports
`windows_terminal_fallback`; it cannot tell which profile a pane uses.

With `icons = "auto"`, Windows chooses font mode when a font registration names
**Herdr Sidebar Logos** and its file exists.

## Remote machines

Each Herdr server decorates only its own panes: a machine attached with
`herdr machine` shows its agents in your sidebar only after the plugin is
installed on that machine too. Run setup there, inside one of its own Herdr
panes. On Windows, run it with the interpreter's absolute path when `python`
could resolve to several installs.

## Manual installation

Use this when preserving a customized sidebar, installing on another terminal,
or keeping later changes to files tracked by setup.

1. Clone the repository and keep that checkout. Back up the files you will edit.
2. Run `herdr plugin link "$PWD" --disabled` from the repository root.
3. Merge [sidebar-layout.toml](../sidebar-layout.toml) into your Herdr config,
   replacing existing `[ui.sidebar.agents]` tables. Set
   `agent_panel_sort = "spaces"` in the existing `[ui]` table. Do not create a
   duplicate `[ui]` table.
4. Run `herdr plugin config-dir testy-cool.herdr-sidebar`. In that directory's
   `config.toml`, set `icons = "text"` for portable labels, or `icons = "font"`
   after completing the font steps below.
5. Run `herdr config check`, then `herdr server reload-config`.
6. Run `herdr plugin enable testy-cool.herdr-sidebar`, then
   `herdr plugin action invoke refresh --plugin testy-cool.herdr-sidebar`.

For font mode, copy `dist/HerdrSidebarLogos-Regular.ttf` to your platform's font
directory in the table above. On Linux, run `fc-cache -f` afterward. On Windows,
use the font file's **Install** command and add the Windows Terminal fallback
[above](#windows). Add this to Ghostty's config, then open a fresh Ghostty process:

```ini
font-codepoint-map = U+E1A0-U+E1A9=Herdr Sidebar Logos
```

The font uses ten private-use codepoints. Only that range is remapped; your
regular terminal font remains in use for text. If another mapping overlaps the
range, resolve it explicitly. Other terminals need their own font fallback or
codepoint mapping configuration; use text mode if unsure.

After a font update, a new window may reuse Ghostty's existing process and cached
font. On Linux, launch `ghostty --gtk-single-instance=false` for a separate
process without closing your current windows or Herdr sessions.

## Manual removal

Use this if setup has no backup, refuses to replace a file edited later, or
cannot undo the sidebar tables in a Herdr config whose layout was hand-edited.

1. Run `herdr plugin action invoke clear --plugin testy-cool.herdr-sidebar` while
   the plugin is enabled, then `herdr plugin disable testy-cool.herdr-sidebar`.
2. Restore only the old `[ui.sidebar.agents]` tables and `agent_panel_sort` from
   your backup, preserving newer unrelated settings. If you had no custom
   sidebar before installation, remove those tables and the sort override to
   return to Herdr defaults.
3. Remove the Herdr Sidebar font mapping from Ghostty. Remove the font only if
   nothing else uses it. Refresh Linux's font cache with `fc-cache -f`. On
   Windows, uninstall the font from Settings → Personalization → Fonts, remove
   the fallback from Windows Terminal's font face, and delete `python-path.txt`
   from the plugin config directory.
4. Run `herdr config check` and `herdr server reload-config`.

The setup backup's `files` object maps absolute paths to `before` (base64 original
bytes, or null if the file did not exist) and `installed_sha256`. Decode selected
`before` values locally to inspect them; do not blindly restore an entire config
over subsequent edits. Retire the old backup after manual recovery before using
automatic setup again. A disabled local plugin registration is harmless and
keeps removal from deleting a user's checkout.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Setup says to run inside Herdr | Open a terminal pane in the intended session; do not spoof `HERDR_ENV` to target an unknown socket. |
| Icons are empty squares | Start a fresh Ghostty process. On Linux, `fc-match 'Herdr Sidebar Logos'` should name that family. Confirm the codepoint mapping above. |
| Icons appear too small or boxed | Confirm the family is **Herdr Sidebar Logos**, not the earlier Herdr Harness Logos font. The bundled Codex outline has no surrounding square. |
| Rows are blank | Run doctor, check the plugin is enabled, and invoke refresh. The custom layout needs the plugin's metadata. |
| A task label is stale | Focus the pane or invoke refresh. Titles update on lifecycle/focus events, not on each byte of terminal output. |
| Tabs look flat | A workspace with one tab deliberately hides tab headings. Add a second tab to see the tree. |
| Doctor reports a failed hook | Inspect `herdr plugin log list --plugin testy-cool.herdr-sidebar --limit 5`. Confirm `python3` is version 3.11 or later in the hook's PATH. On Windows, rerun setup with the intended Python to refresh `python-path.txt`. |
| Windows icons are empty squares | Confirm doctor's `font_registered` and `windows_terminal_fallback`, then open a new Windows Terminal window. |
| Windows uninstall reports access denied | Another program holds the font file. Close Windows Terminal windows that use it and run uninstall again; files already restored are recognized. |

Doctor checks plugin registration, layout, sorting, the latest hook result, and
font files/mapping in explicit font mode (on Windows: the font file, its
registration, and the Windows Terminal fallback). It cannot inspect Ghostty's in-memory
font cache or prove that the user is looking at the same session.
