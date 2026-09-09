# README demo

The README images and recording were captured on 2026-09-08 from an isolated
Herdr 0.8.2 server and Ghostty 1.3.1 window on Linux, using the shipped plugin.
No private working session or conversation is shown.

## What the comparison shows

Both images show the same four demo agents, workspace/tab layout, Vesper theme,
52-column sidebar, and 15-point DejaVu Sans Mono font. The before image uses
Herdr's standard agent rows. The after image uses this repository's installed
sidebar preset and prebuilt provider font. Both are direct captures of the same
624 × 300 screen region; no rows or labels were composited into them.

The demo has two workspaces:

- `sidebar-plugin`: a Runtime tab with a working Codex and blocked Claude, plus
  a Docs tab with a working Codex.
- `icon-font`: one tab with an idle Claude.

Agent identities and lifecycle states were reported through Herdr's demo API
calls. Task names were supplied as terminal titles. They exercise the real
terminal-title fallback, not native conversation-title extraction. No model was
launched and no conversation was manufactured.

## What the recording shows

Actual keyboard interaction with Sidebar settings: enable Dots, select Orbit,
select Pulse, then disable animation. Each choice is saved before showing the
result in the sidebar. The capture runs at eight frames per second, with no
speed-up. Only the relevant region of the isolated terminal is recorded.

## Branch-length recording

The branch-length GIF was recorded separately on 2026-09-09 with the same
Herdr/Ghostty versions, theme, font, and sidebar width. It shows the actual
settings popup switching Standard → Short → Standard. Each selection is saved,
and the resulting live sidebar tokens were checked before continuing. It uses
three reported demo agents in Runtime and Docs tabs, with terminal-title
fallbacks and no running models. The screen recording is eight frames per second
at its original speed; the user's live session was not used.

## Checks

The installation, doctor, removal, and reinstall paths were exercised with
separate config, state, and font directories. Doctor passed. The published
images were checked for readable labels and absence of private shell content.
These captures prove Linux/Ghostty rendering, not macOS compatibility or
many-agent performance.
