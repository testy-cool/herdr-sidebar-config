#!/usr/bin/env python3
"""Install, inspect, or remove Herdr Sidebar. Run inside a Herdr session."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path

from configuration import dimmable_spaces, ghostty_mapping, merge_layout
from runtime import PLUGIN_ID, herdr_binary, run_herdr

ROOT = Path(__file__).resolve().parent
FONT = "HerdrSidebarLogos-Regular.ttf"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def emit(value, as_json=False):
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2))
    else:
        print(value.get("message", value.get("status", "")))
        for path in value.get("files", []):
            print("  " + str(path))
        for line in value.get("notes", []):
            print(line)


def read(path):
    return path.read_bytes() if path.exists() else None


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".herdr-sidebar-tmp")
    temporary.write_bytes(data)
    if path.exists():
        temporary.chmod(path.stat().st_mode & 0o777)
    else:
        temporary.chmod(0o600)
    temporary.replace(path)


def plugin_info(binary):
    result = run_herdr(binary, "plugin", "list", "--json")["result"]
    return next((p for p in result["plugins"] if p["plugin_id"] == PLUGIN_ID), None)


def plugin_config_dir(binary):
    result = subprocess.run([binary, "plugin", "config-dir", PLUGIN_ID],
                            check=True, capture_output=True, text=True, timeout=15)
    return Path(result.stdout.strip())


def invoke(binary, action):
    result = run_herdr(binary, "plugin", "action", "invoke", action, "--plugin", PLUGIN_ID)
    log_id = result["result"]["log"]["log_id"]
    for _ in range(100):
        logs = run_herdr(binary, "plugin", "log", "list", "--plugin", PLUGIN_ID, "--limit", "100")
        log = next((l for l in logs["result"]["logs"] if l["log_id"] == log_id), None)
        if log and log["status"] != "running":
            if log["status"] != "succeeded":
                raise RuntimeError(log.get("stderr") or f"{action} failed")
            return
        time.sleep(0.1)
    raise RuntimeError(f"{action} did not finish within the setup wait period; inspect plugin logs.")


def plan(args, config_dir):
    from configuration import settings_binding
    from preferences import patch
    original = read(args.config) or b""
    preferences_path = config_dir / "config.toml"
    existing = (read(preferences_path) or b"").decode()
    # Normal upgrades retain the chosen icon mode. --text is an explicit choice.
    changes = {"icons": "text"} if args.text else ({"icons": "font"} if "icons" not in tomllib.loads(existing) else {})
    result = {args.config: settings_binding(merge_layout(original.decode(), (ROOT / "sidebar-layout.toml").read_text())).encode(),
              preferences_path: patch(existing, changes).encode()}
    if not args.text:
        result[args.ghostty_config] = ghostty_mapping((read(args.ghostty_config) or b"").decode()).encode()
        result[args.font_dir / FONT] = (ROOT / "dist" / FONT).read_bytes()
    return result


def install(args, binary):
    existing = plugin_info(binary)
    if existing and Path(existing["plugin_root"]).resolve() != ROOT:
        raise RuntimeError("This plugin is installed from another directory. Run setup from that checkout.")
    config_dir = plugin_config_dir(binary)
    files = plan(args, config_dir)
    changes = {p: data for p, data in files.items() if read(p) != data}
    summary = {"status": "planned", "message": "Herdr Sidebar installation plan",
               "files": [str(p) for p in changes], "plugin": PLUGIN_ID,
               "notes": ["Updates agent rows and workspace label dimming; preserves other space metadata.",
                         "Runtime reports display tokens; it does not prompt or stop agents."]}
    if args.dry_run:
        emit(summary, args.json)
        return
    record = args.state_dir / "install.json"
    state = json.loads(record.read_text()) if record.exists() else {"files": {}, "created_link": not bool(existing)}
    classify_preferences(state, config_dir / "config.toml")
    edited = edited_files(state)
    if edited:
        raise RuntimeError("Files changed since setup: " + ", ".join(edited) +
                           ". Keep your edits and use manual installation/removal.")
    # Retain the first backup on repeated installs and updates.
    for path, data in changes.items():
        entry = state["files"].setdefault(str(path), {
            "before": base64.b64encode(read(path)).decode() if path.exists() else None,
        })
        entry["installed_sha256"] = digest(data)
        if path == config_dir / "config.toml":
            entry["user_editable"] = True
    write(record, json.dumps(state, indent=2).encode())
    for path, data in changes.items():
        write(path, data)
    try:
        if not existing:
            run_herdr(binary, "plugin", "link", str(ROOT))
        else:
            run_herdr(binary, "plugin", "enable", PLUGIN_ID)
        check = subprocess.run([binary, "config", "check"], capture_output=True, text=True, timeout=15)
        if check.returncode:
            raise RuntimeError(check.stderr.strip() or check.stdout.strip())
        reload_config(binary)
        invoke(binary, "refresh")
        if not args.text and shutil.which("fc-cache"):
            subprocess.run(["fc-cache", "-f", str(args.font_dir)], check=True, timeout=30)
    except Exception as error:
        # The backup is retained for an explicit uninstall/retry after an API failure.
        raise RuntimeError(f"Setup did not finish: {error}. Config backups are in {record}. Run doctor or uninstall.") from error
    emit({"status": "installed", "message": "Herdr Sidebar is installed and refreshed.",
          "files": summary["files"], "backup": str(record),
          "notes": [] if args.text else ["Open a fresh Ghostty process to load the icon font. Herdr sessions keep running."]}, args.json)


def edited_files(state):
    return [path for path, entry in state["files"].items()
            if not entry.get("user_editable") and
            (read(Path(path)) is None or digest(read(Path(path))) != entry["installed_sha256"])]


def classify_preferences(state, path):
    # Migrate old setup records without discarding their original backup bytes.
    if str(path) in state["files"]:
        state["files"][str(path)]["user_editable"] = True


def reload_config(binary):
    result = run_herdr(binary, "server", "reload-config")["result"]
    if result.get("status") != "applied":
        raise RuntimeError("Herdr rejected config: " + json.dumps(result.get("diagnostics", [])))


def uninstall(args, binary):
    record = args.state_dir / "install.json"
    if not record.exists():
        raise RuntimeError("No setup backup found. Use the README's manual removal steps.")
    state = json.loads(record.read_text())
    classify_preferences(state, plugin_config_dir(binary) / "config.toml")
    edited = edited_files(state)
    if edited:
        raise RuntimeError("These files changed since installation; refusing to overwrite them: " +
                           ", ".join(edited) + f". Original contents are in {record}; see manual removal.")
    summary = {"status": "planned", "message": "Restore backed-up files and disable Herdr Sidebar.",
               "files": [p for p, entry in state["files"].items() if not entry.get("user_editable")]}
    if args.dry_run:
        emit(summary, args.json)
        return
    info = plugin_info(binary)
    if info:
        if info["enabled"]:
            invoke(binary, "clear")
        run_herdr(binary, "plugin", "disable", PLUGIN_ID)
    for path, entry in state["files"].items():
        if entry.get("user_editable"):
            continue
        if entry["before"] is None:
            Path(path).unlink(missing_ok=True)
        else:
            write(Path(path), base64.b64decode(entry["before"]))
    reload_config(binary)
    # Retain the disabled registration so uninstall never deletes the user's checkout.
    record.rename(record.with_name("uninstalled.json"))
    if shutil.which("fc-cache"):
        subprocess.run(["fc-cache", "-f", str(args.font_dir)], check=True, timeout=30)
    emit({"status": "removed", "message": "Original files restored; Herdr Sidebar disabled.",
          "notes": ["The checkout remains available. You can remove it when you no longer need it."]}, args.json)


def doctor(args, binary):
    import tomllib
    info = plugin_info(binary)
    config = tomllib.loads(args.config.read_text()) if args.config.exists() else {}
    actual = config.get("ui", {}).get("sidebar", {}).get("agents", {})
    wanted = tomllib.loads((ROOT / "sidebar-layout.toml").read_text())["ui"]["sidebar"]["agents"]
    logs = run_herdr(binary, "plugin", "log", "list", "--plugin", PLUGIN_ID, "--limit", "1")["result"]["logs"]
    checks = {"plugin_enabled": bool(info and info["enabled"]), "layout_matches": actual == wanted,
              "workspace_dimming": config.get("ui", {}).get("sidebar", {}).get("spaces") == dimmable_spaces(config.get("ui", {}).get("sidebar", {}).get("spaces")),
              "workspace_sort": config.get("ui", {}).get("agent_panel_sort") == "spaces",
              "latest_hook_succeeded": bool(logs and logs[-1]["status"] == "succeeded")}
    settings_path = plugin_config_dir(binary) / "config.toml"
    settings = tomllib.loads(settings_path.read_text()) if settings_path.exists() else {}
    mode = settings.get("icons", "auto")
    checks["icon_mode_valid"] = mode in {"auto", "font", "text"}
    if mode == "font":
        checks["font_installed"] = read(args.font_dir / FONT) == (ROOT / "dist" / FONT).read_bytes()
        checks["ghostty_mapping"] = "font-codepoint-map = U+E1A0-U+E1A8=Herdr Sidebar Logos" in (read(args.ghostty_config) or b"").decode().splitlines()
    emit({"status": "ok" if all(checks.values()) else "needs_attention", "checks": checks,
          "message": "\n".join(f"{'OK' if v else 'CHECK'} {k}" for k,v in checks.items())}, args.json)
    return 0 if all(checks.values()) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["install", "uninstall", "doctor"])
    parser.add_argument("--dry-run", action="store_true", help="show planned file changes without writing")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    parser.add_argument("--text", action="store_true", help="use text labels; do not install or configure a font")
    xdg = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    parser.add_argument("--config", type=Path, default=Path(os.environ.get("HERDR_CONFIG_PATH", str(xdg / "herdr/config.toml"))))
    ghostty = (Path.home() / "Library/Application Support/com.mitchellh.ghostty/config" if sys.platform == "darwin" else xdg / "ghostty/config")
    parser.add_argument("--ghostty-config", type=Path, default=ghostty)
    parser.add_argument("--font-dir", type=Path, default=Path.home() / ("Library/Fonts" if sys.platform == "darwin" else ".local/share/fonts"))
    parser.add_argument("--state-dir", type=Path, help="backup directory; defaults beside the Herdr config")
    args = parser.parse_args()
    default_config = Path(os.environ.get("HERDR_CONFIG_PATH", str(xdg / "herdr/config.toml"))).expanduser().resolve()
    args.config = args.config.expanduser().resolve()
    args.ghostty_config = args.ghostty_config.expanduser().resolve()
    args.font_dir = args.font_dir.expanduser().resolve()
    args.state_dir = (args.state_dir or args.config.parent / "herdr-sidebar-setup").expanduser().resolve()
    try:
        if os.environ.get("HERDR_ENV") != "1":
            raise RuntimeError("Run setup inside a Herdr session (HERDR_ENV=1).")
        if args.config != default_config:
            raise RuntimeError("--config must match the active HERDR_CONFIG_PATH. Run inside the intended Herdr session.")
        binary = herdr_binary()
        run_herdr(binary, "api", "snapshot")
        return {"install": install, "uninstall": uninstall, "doctor": doctor}[args.command](args, binary) or 0
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        emit({"status": "error", "message": str(error)}, args.json)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
