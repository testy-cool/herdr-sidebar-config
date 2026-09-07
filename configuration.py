"""Edit only the sidebar tables; verify the parsed result before any write."""
from __future__ import annotations

import copy
import re
import tomllib

HEADERS = re.compile(r"(?m)^[ \t]*(\[\[?[^\]\n]+\]\]?)[ \t]*(?:#.*)?$")


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
        if name == "ui.sidebar.spaces" or name == "ui.sidebar.agents" or name.startswith("ui.sidebar.agents."):
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


def ghostty_mapping(text):
    mapping = "font-codepoint-map = U+E1A0-U+E1A8=Herdr Sidebar Logos"
    if mapping in text.splitlines():
        return text
    return text.rstrip() + "\n\n# Herdr Sidebar provider icons\n" + mapping + "\n"
