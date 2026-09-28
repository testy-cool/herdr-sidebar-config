"""Edit only the sidebar tables; verify the parsed result before any write."""
from __future__ import annotations

import copy
import re
import tomllib

import host
from runtime import PLUGIN_ID

HEADERS = re.compile(r"(?m)^[ \t]*(\[\[?[^\]\r\n]+\]\]?)[ \t]*(?:#[^\r\n]*)?\r?$")


def settings_binding(text):
    """Use an unclaimed shortcut; never replace a user's existing binding."""
    parsed = tomllib.loads(text)
    def claimed(value):
        if isinstance(value, str):
            return value.lower() in {"prefix+comma", "prefix+,"}
        if isinstance(value, dict):
            return any(claimed(v) for v in value.values())
        return isinstance(value, list) and any(claimed(v) for v in value)
    if claimed(parsed.get("keys", {})):
        return text
    addition = ('\n[[keys.command]]\nkey = "prefix+comma"\ntype = "plugin_action"\n'
                f'command = "{PLUGIN_ID}.{host.entry("settings")}"\ndescription = "Sidebar settings"\n')
    result = text.rstrip() + "\n" + addition
    expected = copy.deepcopy(parsed)
    expected.setdefault("keys", {}).setdefault("command", []).append(tomllib.loads(addition)["keys"]["command"][0])
    if tomllib.loads(result) != expected:
        raise ValueError("Cannot safely add the sidebar settings shortcut.")
    return result


def dimmable_spaces(spaces):
    """Replace just the workspace label; retain the user's branches and spacing."""
    result = copy.deepcopy(spaces or {"rows": [["state_icon", "workspace"], ["branch", "git_status"]]})
    rows = result.get("rows", [["state_icon", "workspace"], ["branch", "git_status"]])
    result["rows"] = []
    for row in rows:
        tokens = []
        for token in row:
            name = token if isinstance(token, str) else token.get("token")
            if name == "workspace":
                style = {} if isinstance(token, str) else dict(token)
                tokens += [dict(style, token="$hs_space", dim=False),
                           dict(style, token="$hs_space_dim", dim=True)]
            else:
                tokens.append(token)
        result["rows"].append(tokens)
    return result


def spaces_fragment(spaces):
    import json
    lines = ["[ui.sidebar.spaces]"]
    for key, value in spaces.items():
        if key == "rows":
            rows = []
            for row in value:
                parts = []
                for token in row:
                    if isinstance(token, str):
                        parts.append(json.dumps(token))
                    else:
                        parts.append("{ " + ", ".join(k + " = " + json.dumps(v) for k, v in token.items()) + " }")
                rows.append("[" + ", ".join(parts) + "]")
            lines.append("rows = [" + ", ".join(rows) + "]")
        else:
            lines.append(key + " = " + json.dumps(value))
    return "\n".join(lines)


def sections(text):
    matches = list(HEADERS.finditer(text))
    return [(m.start(), matches[i + 1].start() if i + 1 < len(matches) else len(text),
             m.group(1).strip("[]").strip()) for i, m in enumerate(matches)]


def merge_layout(text, fragment):
    before = tomllib.loads(text)
    layout = tomllib.loads(fragment)["ui"]["sidebar"]["agents"]
    expected = copy.deepcopy(before)
    ui = expected.setdefault("ui", {})
    ui["agent_panel_sort"] = "spaces"
    ui.setdefault("sidebar", {})["agents"] = layout
    spaces = dimmable_spaces(ui["sidebar"].get("spaces"))
    ui["sidebar"]["spaces"] = spaces
    if before == expected:
        return text

    # Keep unrelated tables, comments, keybindings, and terminal settings intact.
    result = text
    for start, end, name in reversed(sections(text)):
        if _owned(name):
            result = result[:start] + result[end:]
    ui_section = next(((a, b) for a, b, name in sections(result) if name == "ui"), None)
    if ui_section:
        start, end = ui_section
        block = result[start:end]
        setting = re.compile(r'(?m)^[ \t]*agent_panel_sort[ \t]*=.*$')
        if setting.search(block):
            block = setting.sub('agent_panel_sort = "spaces"', block)
        else:
            newline = block.find("\n")
            if newline < 0:
                block += '\nagent_panel_sort = "spaces"\n'
            else:
                block = block[:newline + 1] + 'agent_panel_sort = "spaces"\n' + block[newline + 1:]
        result = result[:start] + block + result[end:]
    else:
        result = result.rstrip() + '\n\n[ui]\nagent_panel_sort = "spaces"\n'
    result = result.rstrip() + "\n\n" + fragment.strip() + "\n\n" + spaces_fragment(spaces) + "\n"
    try:
        actual = tomllib.loads(result)
    except tomllib.TOMLDecodeError as error:
        raise ValueError("Cannot safely edit this TOML layout; use the manual installation steps.") from error
    if actual != expected:
        raise ValueError("Config contains an unsupported table form; no settings were written. Use manual installation.")
    return result


def _owned(name):
    return name == "ui.sidebar.spaces" or name == "ui.sidebar.agents" or name.startswith("ui.sidebar.agents.")


def _binding(block):
    return f'command = "{PLUGIN_ID}.' in block


def restore_layout(text, original, fragment):
    """Undo merge_layout(original, fragment) and settings_binding on a config
    edited since setup.

    The sidebar tables, the sort order and the settings shortcut return to
    ``original``; every later edit elsewhere stays.
    """
    current, before = tomllib.loads(text), tomllib.loads(original)
    expected = copy.deepcopy(current)
    ui, ui_before = expected.setdefault("ui", {}), before.get("ui", {})
    sidebar, sidebar_before = ui.setdefault("sidebar", {}), ui_before.get("sidebar", {})
    for key in ("agents", "spaces"):
        if key in sidebar_before:
            sidebar[key] = sidebar_before[key]
        else:
            sidebar.pop(key, None)
    if not sidebar and "sidebar" not in ui_before:
        ui.pop("sidebar")
    if "agent_panel_sort" in ui_before:
        ui["agent_panel_sort"] = ui_before["agent_panel_sort"]
    else:
        ui.pop("agent_panel_sort", None)
    if not ui and "ui" not in before:
        expected.pop("ui")
    added = not any(_binding(original[a:b]) for a, b, name in sections(original) if name == "keys.command")
    keys = expected.get("keys", {})
    if added and "command" in keys:
        keys["command"] = [c for c in keys["command"] if not str(c.get("command", "")).startswith(PLUGIN_ID + ".")]
        if not keys["command"] and "command" not in before.get("keys", {}):
            keys.pop("command")
            if not keys and "keys" not in before:
                expected.pop("keys")

    # The fragment's leading comment travels with it; it now heads no table.
    preamble = fragment[:next(HEADERS.finditer(fragment)).start()].strip()
    result = text
    if preamble and preamble not in original:
        result = re.sub(r"(?m)^" + re.escape(preamble) + r"\r?\n", "", result, count=1)
    for start, end, name in reversed(sections(result)):
        if _owned(name) or (added and name == "keys.command" and _binding(result[start:end])):
            result = result[:start] + result[end:]
    setting = re.compile(r'(?m)^[ \t]*agent_panel_sort[ \t]*=.*\n?')
    old = next((setting.search(original[a:b]) for a, b, name in sections(original) if name == "ui"), None)
    for start, end, name in sections(result):
        if name == "ui":
            block = setting.sub(old.group(0) if old else "", result[start:end], count=1)
            # setup wrote this [ui] header only to hold the sort order.
            if not any(name == "ui" for _, _, name in sections(original)) and not block.partition("\n")[2].strip():
                block = ""
            result = result[:start] + block + result[end:]
            break
    kept = "".join(original[a:b] for a, b, name in sections(original) if _owned(name))
    if kept:
        result = result.rstrip() + "\n\n" + kept.strip() + "\n"
    try:
        actual = tomllib.loads(result)
    except tomllib.TOMLDecodeError as error:
        raise ValueError("Cannot safely restore this TOML layout; use manual removal.") from error
    if actual != expected:
        raise ValueError("Config changed in a way setup cannot undo; use manual removal.")
    return result


GHOSTTY_MAPPING = "font-codepoint-map = U+E1A0-U+E1A9=Herdr Sidebar Logos"


def ghostty_mapping(text):
    text = text.replace("U+E1A0-U+E1A8=Herdr Sidebar Logos", "U+E1A0-U+E1A9=Herdr Sidebar Logos")
    if GHOSTTY_MAPPING in text.splitlines():
        return text
    return text.rstrip() + "\n\n# Herdr Sidebar provider icons\n" + GHOSTTY_MAPPING + "\n"
