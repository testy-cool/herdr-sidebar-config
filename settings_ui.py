"""A quiet, dependency-free settings popup. No redraw until input or resize."""
import curses
from pathlib import Path

import preferences
from runtime import PLUGIN_ID, herdr_binary, run_herdr

FIELDS = [("order", "Order", ["workspace", "activity"]),
          ("icons", "Icons", ["auto", "font", "text"]),
          ("inactive_after_seconds", "Dim after (minutes)", None),
          ("animated_loaders", "Animated loaders", [False, True])]
LABELS = {"auto": "Automatic", "font": "Font", "text": "Text",
          "workspace": "Workspace order", "activity": "Active groups first", False: "Off", True: "On"}


def open_popup():
    run_herdr(herdr_binary(), "plugin", "pane", "open", "--plugin", PLUGIN_ID,
              "--entrypoint", "settings", "--cwd", str(Path(__file__).resolve().parent))


def editor(screen):
    curses.curs_set(0)
    if curses.has_colors():
        curses.use_default_colors()
        curses.init_pair(1, -1, -1)
        screen.bkgd(' ', curses.color_pair(1))
    screen.keypad(True)
    path = preferences.settings_path()
    original = path.read_text() if path.exists() else ""
    values = preferences.load(path)
    initial = dict(values)
    selected, message, number = 0, "", ""

    def draw(y, text, style=0):
        height, width = screen.getmaxyx()
        if y < height - 1 and width > 4:
            screen.addnstr(y, 2, text, width - 4, style)

    while True:
        screen.erase()
        draw(1, "Sidebar settings", curses.A_BOLD)
        if FIELDS[selected][0] == "animated_loaders":
            draw(2, "On uses extra CPU while agents work.")
        for index, (key, label, options) in enumerate(FIELDS):
            value = values[key]
            display = LABELS.get(value, str(value)) if options else f"{value / 60:g}"
            if index == selected and number:
                display = number
            draw(3 + index, f"{label:<25} {display}", curses.A_REVERSE if index == selected else 0)
        draw(5 + len(FIELDS), "↑↓ select   ←→ change   Type minutes")
        draw(6 + len(FIELDS), "Enter save and close   Esc cancel")
        draw(8 + len(FIELDS), message)
        screen.refresh()
        key = screen.get_wch()
        if key in ("\x1b", "q"):
            return
        if key in ("\n", "\r", curses.KEY_ENTER):
            try:
                if number:
                    values["inactive_after_seconds"] = float(number) * 60
                changes = {k: v for k, v in values.items() if k in preferences.DEFAULTS and v != initial[k]}
                preferences.save(path, original, changes)
                original = path.read_text() if path.exists() else ""
                # The popup already has plugin context. Apply synchronously so
                # an API failure stays visible instead of reporting false success.
                from sidebar import refresh
                refresh(restore_view=True)
                return
            except (ValueError, RuntimeError, OSError) as error:
                message = str(error)
        elif key in (curses.KEY_UP, curses.KEY_DOWN):
            if number:
                try:
                    values["inactive_after_seconds"] = float(number) * 60
                except ValueError:
                    message = "Enter a positive number of minutes."
                number = ""
            selected = (selected + (1 if key == curses.KEY_DOWN else -1)) % len(FIELDS)
        elif key in (curses.KEY_LEFT, curses.KEY_RIGHT):
            field, _, options = FIELDS[selected]
            direction = 1 if key == curses.KEY_RIGHT else -1
            if options:
                values[field] = options[(options.index(values[field]) + direction) % len(options)]
            else:
                values[field] = max(60, values[field] + direction * 60)
            number, message = "", ""
        elif FIELDS[selected][0] == "inactive_after_seconds":
            if isinstance(key, str) and key in "0123456789.":
                number += key
            elif key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                number = number[:-1]


def main():
    curses.wrapper(editor)
