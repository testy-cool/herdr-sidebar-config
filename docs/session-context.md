# Saved conversation context

The sidebar reads existing agent conversations. It makes no model calls, sends
no prompts and does not wake agents. Workspace names remain user-owned.

Enable **Conversation tab titles** in Sidebar settings (off by default).
Generic names (`main`, `shell`, `terminal`, `tab`, numbered tabs) become a saved
session title, or the latest meaningful user request when no native title exists.
Names are shortened to 40 characters at word boundaries. Distinct assignments
in one tab are listed with `/`; more than two get a remaining count. A manual
rename, including a pin marker, takes priority. An automatic name is updated only
while the tab label matches the last write. Sleeping tabs are never renamed.
Turning the option off or removing the plugin keeps the useful native names;
rename a tab to `main` to opt it in again.

## Read sleeping work

Select its tab in Spaces and use **Show saved conversation context** (plugin
action `context`, or `context-windows` on Windows). The popup shows full titles, latest meaningful requests,
native lifecycle status or validated Hibernate sleeping state, source and recorded
time. Requests wrap; Up/Down scroll and PgUp/PgDn move a page. Esc closes without resuming. It does not infer
results or next steps. Sleeping context stays in this popup; Spaces has no extra
sleeping-agent row. Sleeping panes remain terminals without an Agents-panel anchor.

## Local data

Codex reads its read-only thread database to locate the exact rollout, with
native title/index and exact-session history fallbacks. Claude reads its exact
project/session file and history. Pi reads its reported session file or exact
session-ID file. Transcript tails are bounded to 512 KiB. Images, tools, injected
instructions and vague follow-ups do not become titles. Unsupported agents keep
the existing terminal-title fallback.

`context.json` is an atomic UTF-8 file in the per-user plugin state directory
(mode 0600 on POSIX; inherited directory permissions on Windows). It
stores short title/request facts, session identity, pane/tab/workspace links, cwd
and recorded time, without full conversations or Hibernate resume commands.
Closed panes are pruned; reused panes cannot inherit another session's context.
The agent-exit gap retains a private record without prematurely showing sleep.

Hibernate's `~/.config/herdr-hibernate/state.json` is read-only. Pane, tab and cwd
must match before accepting its session record. Workspace identity comes from
Herdr's native pane; if Hibernate records a workspace, that must match too.
This also supports older Hibernate records without a workspace field. Existing
sleeping sessions recover context from saved conversations on first install.
`HERDR_SIDEBAR_HIBERNATE_STATE` overrides the path for isolated testing. Delete
the cache when its retained request text is no longer wanted; provider files are
never changed.
