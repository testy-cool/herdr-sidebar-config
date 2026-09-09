"""User-owned preferences, with conservative, comment-preserving TOML edits."""
import json
import math
import os
from pathlib import Path
import re
import tempfile
import tomllib

DEFAULTS = {"icons": "auto", "inactive_after_seconds": 600, "order": "workspace",
            "animated_loaders": False, "loader_style": "dots", "branch_length": "standard"}


def settings_path():
    return Path(os.environ["HERDR_PLUGIN_CONFIG_DIR"]) / "config.toml"


def validate(values):
    result = dict(DEFAULTS, **values)
    if result["icons"] not in ("auto", "font", "text"):
        raise ValueError("Icons must be automatic, font, or text.")
    if result["order"] not in ("workspace", "activity"):
        raise ValueError("Order must be workspace or activity.")
    if not isinstance(result["animated_loaders"], bool):
        raise ValueError("Animated loaders must be on or off.")
    if result["loader_style"] not in ("dots", "orbit", "pulse"):
        raise ValueError("Loader style must be dots, orbit, or pulse.")
    if result["branch_length"] not in ("standard", "short"):
        raise ValueError("Branch length must be standard or short.")
    delay = result["inactive_after_seconds"]
    if isinstance(delay, bool) or not isinstance(delay, (int, float)) or not math.isfinite(delay) or delay <= 0:
        raise ValueError("Dimming delay must be a positive number of minutes.")
    return result


def load(path=None):
    path = path or settings_path()
    return validate(tomllib.loads(path.read_text()) if path.exists() else {})


def patch(text, changes):
    before = tomllib.loads(text)
    if set(changes) - DEFAULTS.keys():
        raise ValueError("Unknown sidebar preference.")
    expected = dict(before, **changes)
    validate(expected)
    result = text
    for key, value in changes.items():
        if before.get(key) == value:
            continue
        # Only top-level scalar preferences are ours. Parsed equality below
        # rejects dotted keys, multiline tricks, or other unsupported forms.
        table = re.search(r"(?m)^\s*\[", result)
        stop = table.start() if table else len(result)
        head, tail = result[:stop], result[stop:]
        pattern = re.compile(r'(?m)^([ \t]*(?:' + re.escape(key) + r'|"' + re.escape(key)
                             + r'")[ \t]*=[ \t]*)([^#\r\n]*?)([ \t]*(?:#[^\r\n]*)?)(\r?\n|$)')
        rendered = json.dumps(value)
        if pattern.search(head):
            head = pattern.sub(lambda m: m[1] + rendered + m[3] + m[4], head, count=1)
        else:
            head = head.rstrip("\n") + ("\n" if head else "") + key + " = " + rendered + "\n"
        result = head + tail
    if tomllib.loads(result) != expected:
        raise ValueError("Cannot safely edit these preferences; original file was kept.")
    return result


def save(path, original, changes):
    current = path.read_text() if path.exists() else ""
    if current != original:
        raise ValueError("Settings changed elsewhere. Close and reopen this popup.")
    result = patch(original, changes)
    if result == current:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(result)
        temporary.chmod(path.stat().st_mode & 0o777 if path.exists() else 0o600)
        temporary.replace(path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
    return True
