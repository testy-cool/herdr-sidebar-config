# Setup and troubleshooting

Use the [README quick start](../README.md#install) for the supported installation
flow. Run setup from the same checkout and Herdr session each time.

## Files setup manages

Open **Sidebar settings** from the command palette or press `prefix+,` (setup
adds this shortcut only when unclaimed). Arrow keys change icons and the dimming
delay; type a number on the minutes row for an exact delay. Enter saves and
applies once; Escape cancels. You can also open it with:

```sh
herdr plugin action invoke settings --plugin testy-cool.herdr-sidebar
```

Plugin preferences are user-owned. Updates retain them, `--text` explicitly
selects text icons, and uninstall leaves preferences available for a later
reinstall. Older setup backups are migrated without losing their original bytes.

| Item | Default location |
| --- | --- |
| Herdr layout | `$XDG_CONFIG_HOME/herdr/config.toml`, or `~/.config/herdr/config.toml` |
| Plugin icon setting | The directory printed by `herdr plugin config-dir testy-cool.herdr-sidebar`, then `config.toml` |
| Linux font | `~/.local/share/fonts/HerdrSidebarLogos-Regular.ttf` |
| macOS font | `~/Library/Fonts/HerdrSidebarLogos-Regular.ttf` |
| Linux Ghostty config | `$XDG_CONFIG_HOME/ghostty/config`, or `~/.config/ghostty/config` |
| macOS Ghostty config | `~/Library/Application Support/com.mitchellh.ghostty/config` |
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
publish them. Repeated installs retain the first backup. Setup and removal stop
if a managed layout/font file has since changed; editable plugin preferences are
excluded from that guard and from restoration. An interrupted setup retains its backup for
inspection and recovery. The helper is intended for one active session at a
time; other running sessions that share the config may need their own refresh.

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
directory in the table above. On Linux, run `fc-cache -f` afterward. Add this to
Ghostty's config, then open a fresh Ghostty process:

```ini
font-codepoint-map = U+E1A0-U+E1A8=Herdr Sidebar Logos
```

The font uses nine private-use codepoints. Only that range is remapped; your
regular terminal font remains in use for text. If another mapping overlaps the
range, resolve it explicitly. Other terminals need their own font fallback or
codepoint mapping configuration; use text mode if unsure.

## Manual removal

Use this if setup has no backup or refuses to replace a file edited later.

1. Run `herdr plugin action invoke clear --plugin testy-cool.herdr-sidebar` while
   the plugin is enabled, then `herdr plugin disable testy-cool.herdr-sidebar`.
2. Restore only the old `[ui.sidebar.agents]` tables and `agent_panel_sort` from
   your backup, preserving newer unrelated settings. If you had no custom
   sidebar before installation, remove those tables and the sort override to
   return to Herdr defaults.
3. Remove the Herdr Sidebar font mapping from Ghostty. Remove the font only if
   nothing else uses it. Refresh Linux's font cache with `fc-cache -f`.
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
| Doctor reports a failed hook | Inspect `herdr plugin log list --plugin testy-cool.herdr-sidebar --limit 5`. Confirm `python3` is version 3.11 or later in the hook's PATH. |

Doctor checks plugin registration, layout, sorting, the latest hook result, and
font files/mapping in explicit font mode. It cannot inspect Ghostty's in-memory
font cache or prove that the user is looking at the same session.
