#!/usr/bin/env python3
"""Validate the knowledge docs: relative links, anchors, and registry facts.

Read-only. Used by tests/test_knowledge_docs.py and by hand:

    python3 tools/check_knowledge_docs.py
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE = ROOT / "docs" / "knowledge"
REGISTRY = KNOWLEDGE / "registry.json"

LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
FENCE = re.compile(r"^```")
ENV = re.compile(r"os\.environ(?:\[|\.get\(\s*)['\"]([A-Z0-9_]+)['\"]")
TOKEN = re.compile(r"\bhs_[a-z_]{2,}\b")
PLACEHOLDER = re.compile(r"\b(?:TODO|TBD|FIXME|XXX)\b|lorem ipsum|\?\?\?", re.I)
HEX_REF = re.compile(r"^[0-9a-f]{7,40}$")
SLUG_DROP = re.compile(r"[^\w\s-]")


def markdown_files():
    files = [ROOT / "README.md", ROOT / "AGENTS.md"]
    for directory in (ROOT / "docs", KNOWLEDGE):
        files.extend(sorted(directory.rglob("*.md")))
    return sorted({path for path in files if path.exists()})


def slug(text):
    text = re.sub(r"`", "", text)
    return SLUG_DROP.sub("", text.lower()).strip().replace(" ", "-")


def anchors(path):
    found, fenced = set(), False
    for line in path.read_text(encoding="utf-8").splitlines():
        if FENCE.match(line):
            fenced = not fenced
        elif not fenced:
            match = HEADING.match(line)
            if match:
                found.add(slug(match.group(2)))
    return found


def prose_links(path):
    """Yield (target, anchor) for links outside fenced code blocks."""
    fenced = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        for target in LINK.findall(line):
            if target.startswith(("http://", "https://", "mailto:", "#", "<")):
                if target.startswith("#"):
                    yield path, target[1:]
                continue
            file_part, _, anchor = target.partition("#")
            yield (path.parent / file_part).resolve(), anchor or None


def check_links():
    failures = []
    cache = {}
    for path in markdown_files():
        for target, anchor in prose_links(path):
            try:
                shown = target.relative_to(ROOT)
            except ValueError:
                shown = target
            if not target.exists():
                failures.append(f"{path.relative_to(ROOT)}: missing target {shown}")
                continue
            if anchor:
                if target not in cache:
                    cache[target] = anchors(target)
                if anchor not in cache[target]:
                    failures.append(f"{path.relative_to(ROOT)}: missing anchor #{anchor} in {shown}")
    return failures


def check_placeholders():
    failures = []
    for path in sorted(KNOWLEDGE.rglob("*.md")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = PLACEHOLDER.search(line)
            if match:
                failures.append(f"{path.relative_to(ROOT)}:{number}: placeholder {match.group(0)!r}")
    return failures


def check_doc_tokens():
    """Every hs_* name the knowledge docs mention must be a registry token."""
    known = {entry["name"] for entry in registry()["tokens"]}
    failures = []
    for path in sorted(KNOWLEDGE.rglob("*.md")):
        for name in sorted(set(TOKEN.findall(path.read_text(encoding="utf-8"))) - known):
            failures.append(f"{path.relative_to(ROOT)}: names unknown token {name}")
    return failures


def source_tokens():
    names = set()
    for name in ("sidebar.py", "ordering.py", "animation.py", "inactivity.py"):
        names.update(TOKEN.findall((ROOT / name).read_text(encoding="utf-8")))
    return names - {"hs_"}


def source_env():
    names = set()
    for path in sorted(ROOT.glob("*.py")):
        names.update(ENV.findall(path.read_text(encoding="utf-8")))
    return names


def registry():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def check_registry():
    data = registry()
    failures = []
    if not HEX_REF.fullmatch(data.get("inspected_ref", "")):
        failures.append("registry: inspected_ref is not a git object hash")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data.get("verified_date", "")):
        failures.append("registry: verified_date is not an ISO date")

    sys.path.insert(0, str(ROOT))
    import preferences
    import runtime
    import settings_ui

    documented = {entry["key"]: entry for entry in data["preferences"]}
    if set(documented) != set(preferences.DEFAULTS):
        failures.append("registry: preference keys differ from preferences.DEFAULTS")
    popup = [field[0] for field in settings_ui.FIELDS]
    if sorted(popup) != sorted(preferences.DEFAULTS):
        failures.append("registry: settings popup fields differ from preferences.DEFAULTS")
    for key, entry in documented.items():
        if entry.get("default") != preferences.DEFAULTS[key]:
            failures.append(f"registry: default for {key} differs from preferences.DEFAULTS")
        for value in entry.get("values", []):
            try:
                preferences.validate({key: value})
            except ValueError:
                failures.append(f"registry: documented value {value!r} rejected for {key}")

    import sidebar

    layout = (ROOT / "sidebar-layout.toml").read_text(encoding="utf-8")
    layout_tokens = set(TOKEN.findall(layout))
    literals = source_tokens()
    states = {f"hs_{state}" for state in sidebar.STATES}
    # The dim twins are generated by the loop in sidebar.desired_rows, and the
    # spacer/gap/rank/title/focus tokens deliberately have no twin.
    untwinned = {"hs_gap", "hs_workspace_rank", "hs_title", "hs_logo_focus", "hs_terminals", "hs_parked",
                 *sidebar.ACCENT_LOGOS.values()}
    dims = {name + "_dim" for name in literals | states
            if name not in untwinned and not name.endswith("_dim")}
    tokens = {entry["name"]: entry for entry in data["tokens"]}
    if literals | states | dims != set(tokens):
        failures.append("registry: token list differs from the tokens the runtime publishes")
    for name, entry in tokens.items():
        consumed = entry.get("consumed_by")
        if consumed == "layout" and name not in layout_tokens:
            failures.append(f"registry: {name} claims layout use but is absent from sidebar-layout.toml")
        if consumed == "none" and name in layout_tokens:
            failures.append(f"registry: {name} is marked unused but appears in sidebar-layout.toml")
    for name in layout_tokens - set(tokens):
        failures.append(f"registry: sidebar-layout.toml uses {name} with no registry entry")

    providers = {entry["agent"]: entry for entry in data["providers"]}
    if set(providers) != set(runtime.PUA_LOGOS):
        failures.append("registry: provider list differs from runtime.PUA_LOGOS")
    for agent, entry in providers.items():
        if entry.get("codepoint") != f"{ord(runtime.PUA_LOGOS[agent]):04X}":
            failures.append(f"registry: codepoint for {agent} differs from runtime.PUA_LOGOS")
        if entry.get("text_label") != runtime.TEXT_LOGOS.get(agent):
            failures.append(f"registry: text label for {agent} differs from runtime.TEXT_LOGOS")

    import tomllib
    codepoints = tomllib.loads((ROOT / "font" / "codepoints.toml").read_text(encoding="utf-8"))["glyphs"]
    for agent, entry in providers.items():
        if codepoints.get(agent) != entry.get("codepoint"):
            failures.append(f"registry: codepoint for {agent} differs from font/codepoints.toml")

    for entry in data["fonts"]:
        path = ROOT / entry["path"]
        if not path.exists():
            failures.append(f"registry: font {entry['path']} is missing")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            failures.append(f"registry: sha256 for {entry['path']} does not match the committed file")

    for group, directory, pattern in (("modules", ROOT, "*.py"), ("tools", ROOT / "tools", "*.py"),
                                      ("tests", ROOT / "tests", "*.py")):
        listed = {entry["path"] for entry in data[group]}
        present = {path.relative_to(ROOT).as_posix() for path in sorted(directory.glob(pattern))}
        if listed != present:
            failures.append(f"registry: {group} list differs from the files on disk: {sorted(present - listed)}")

    if source_env() != {entry["name"] for entry in data["env"]}:
        failures.append("registry: environment variables differ from the ones the runtime reads")

    setup_source = (ROOT / "setup_sidebar.py").read_text(encoding="utf-8")
    for entry in data["managed_paths"]:
        for probe in entry.get("probe", []):
            if probe not in setup_source and probe not in (ROOT / "configuration.py").read_text(encoding="utf-8"):
                failures.append(f"registry: managed path {entry['name']} probe {probe!r} is not in the installer")

    for entry in data["evidence"]:
        if entry.get("class") not in {"observed", "accepted", "proposed", "historical", "unknown"}:
            failures.append(f"registry: evidence {entry.get('id')} has no valid class")
        if not entry.get("source"):
            failures.append(f"registry: evidence {entry.get('id')} has no source")
    return failures


def check_all():
    return check_links() + check_placeholders() + check_doc_tokens() + check_registry()


def main():
    failures = check_all()
    for line in failures:
        print("FAIL " + line)
    print(f"{len(failures)} failure(s); {len(markdown_files())} markdown file(s) checked")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
