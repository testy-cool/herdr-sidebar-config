"""A quiet, dependency-free settings popup. No redraw until input or resize."""
from pathlib import Path

import host
import preferences
from runtime import PLUGIN_ID, herdr_binary, run_herdr

FIELDS = [("order", "Order", ["workspace", "activity"]),
          ("icons", "Icons", ["auto", "font", "text"]),
          ("inactive_after_seconds", "Dim after (minutes)", None),
          ("animated_loaders", "Animated loaders", [False, True]),
          ("loader_style", "Loader style", ["dots", "orbit", "pulse"]),
          ("branch_length", "Branch length", ["standard", "short"])]
LABELS = {"auto": "Automatic", "font": "Font", "text": "Text",
          "workspace": "Workspace order", "activity": "Active groups first", False: "Off", True: "On",
          "dots": "Dots", "orbit": "Orbit", "pulse": "Pulse",
          "standard": "Standard  ├─  └─", "short": "Short     ├   └"}


def open_popup():
    run_herdr(herdr_binary(), "plugin", "pane", "open", "--plugin", PLUGIN_ID,
              "--entrypoint", host.entry("settings"), "--cwd", str(Path(__file__).resolve().parent))


def apply_now():
    # The popup already has plugin context. Apply synchronously so an API
    # failure stays visible instead of reporting false success.
    from sidebar import refresh
    refresh(restore_view=True)


def editor(terminal, path=None, apply=apply_now):
    path = path or preferences.settings_path()
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    values = preferences.load(path)
    initial = dict(values)
    selected, message, number = 0, "", ""

    def draw(y, text, style=None):
        height, width = terminal.size()
        if y < height - 1 and width > 4:
            terminal.draw(y, 2, text[:width - 4], style)

    while True:
        terminal.clear()
        draw(1, "Sidebar settings", "bold")
        if FIELDS[selected][0] == "animated_loaders":
            draw(2, "On uses extra CPU while agents work.")
        elif FIELDS[selected][0] == "loader_style":
            draw(2, {"dots": "Rotating dot trail. Requires Animated loaders: On.",
                     "orbit": "One dot orbiting the cell. Requires loaders: On.",
                     "pulse": "Rising and falling dots. Requires loaders: On."}[values["loader_style"]])
        for index, (key, label, options) in enumerate(FIELDS):
            value = values[key]
            display = LABELS.get(value, str(value)) if options else f"{value / 60:g}"
            if index == selected and number:
                display = number
            draw(3 + index, f"{label:<25} {display}", "reverse" if index == selected else None)
        draw(5 + len(FIELDS), "↑↓ select   ←→ change   Type minutes")
        draw(6 + len(FIELDS), "Enter save and close   Esc cancel")
        draw(8 + len(FIELDS), message)
        terminal.refresh()
        key = terminal.key()
        if key in ("escape", "q"):
            return
        if key == "enter":
            try:
                if number:
                    values["inactive_after_seconds"] = float(number) * 60
                changes = {k: v for k, v in values.items() if k in preferences.DEFAULTS and v != initial[k]}
                preferences.save(path, original, changes)
                original = path.read_text(encoding="utf-8") if path.exists() else ""
                apply()
                return
            except (ValueError, RuntimeError, OSError) as error:
                message = str(error)
        elif key in ("up", "down"):
            if number:
                try:
                    values["inactive_after_seconds"] = float(number) * 60
                except ValueError:
                    message = "Enter a positive number of minutes."
                number = ""
            selected = (selected + (1 if key == "down" else -1)) % len(FIELDS)
        elif key in ("left", "right"):
            field, _, options = FIELDS[selected]
            direction = 1 if key == "right" else -1
            if options:
                values[field] = options[(options.index(values[field]) + direction) % len(options)]
            else:
                values[field] = max(60, values[field] + direction * 60)
            number, message = "", ""
        elif FIELDS[selected][0] == "inactive_after_seconds":
            if len(key) == 1 and key in "0123456789.":
                number += key
            elif key == "backspace":
                number = number[:-1]


def main():
    with host.terminal() as terminal:
        editor(terminal)
