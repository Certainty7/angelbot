#!/usr/bin/env python3
"""Generate the Angel website's static command catalogue and invite facts from the bot source.

The website is static, so every number it publishes is derived here, at build time, from the
checked-out repository: no backend, no database, no hand-maintained list that can drift.

Discovery is AST-based on purpose. A `grep -r "@app_commands.command"` counts decorators, not
registered commands: it also matches the decorator text in comments, and it cannot tell a command
that is attached to the tree from one whose cog is never installed. This script parses the modules
that the bot actually loads (bot.py imports + install(), plus the lazy extension in
angel/client.py) and refuses to emit anything when a decorated command lives in an unloaded module.

Usage:
    python3 tools/website-data-generator/generate.py                 # write the data files
    python3 tools/website-data-generator/generate.py --check         # fail if they are stale
    python3 tools/website-data-generator/generate.py --print-summary

Outputs (relative to --out, default `website/src/data`):
    commands.json   categories, totals and every registered command
    invite.json     application id, required bot permissions (with evidence) and the invite URL
    changelog.json  releases parsed from CHANGELOG.md and CHANGELOG.ar.md
    site.json       version, license, repository and derived site facts
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import sys
from urllib.parse import urlparse

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent

SKIP_DIRS = {
    ".git", "venv", ".venv", "env", "node_modules", "__pycache__", "dist", "build",
    "tests", "website", "tools", "docs", "deploy", ".github", ".mypy_cache", ".ruff_cache",
}

# module -> (id, English label, Arabic label). A module that is not listed falls back to its own
# name, so adding a cog to the bot degrades gracefully instead of dropping commands.
CATEGORIES = {
    "admin": ("admin", "Administration", "الإدارة"),
    "community": ("community", "Community", "المجتمع"),
    "flagship": ("flagship", "Control Center", "مركز التحكم"),
    "memory_rules": ("memory_rules", "Memory & Rules", "الذاكرة والقوانين"),
    "owner": ("owner", "Owner Tools", "أدوات المالك"),
    "ai_chat": ("ai_chat", "AI & Chat", "الذكاء والمحادثة"),
    "music": ("music", "Music", "الموسيقى"),
    "control": ("control", "Controls", "التحكم"),
    "context_menus": ("context_menus", "Context Menus", "قوائم السياق"),
    "productivity": ("productivity", "Productivity", "الإنتاجية"),
    "media_tools": ("media_tools", "Media Tools", "أدوات الوسائط"),
    "fun_gif": ("fun_gif", "Fun & GIFs", "المرح والصور المتحركة"),
    "xp_profile": ("xp_profile", "Profile & XP", "الملف والمستويات"),
}

# Discord permission bit positions (https://discord.com/developers/docs/topics/permissions).
PERMISSION_BITS = {
    "create_instant_invite": 0, "kick_members": 1, "ban_members": 2, "administrator": 3,
    "manage_channels": 4, "manage_guild": 5, "add_reactions": 6, "view_audit_log": 7,
    "priority_speaker": 8, "stream": 9, "view_channel": 10, "send_messages": 11,
    "send_tts_messages": 12, "manage_messages": 13, "embed_links": 14, "attach_files": 15,
    "read_message_history": 16, "mention_everyone": 17, "use_external_emojis": 18,
    "view_guild_insights": 19, "connect": 20, "speak": 21, "mute_members": 22,
    "deafen_members": 23, "move_members": 24, "use_vad": 25, "change_nickname": 26,
    "manage_nicknames": 27, "manage_roles": 28, "manage_webhooks": 29,
    "manage_guild_expressions": 30, "use_application_commands": 31, "request_to_speak": 32,
    "manage_events": 33, "manage_threads": 34, "create_public_threads": 35,
    "create_private_threads": 36, "use_external_stickers": 37, "send_messages_in_threads": 38,
    "use_embedded_activities": 39, "moderate_members": 40,
}

COMMAND_DECORATORS = {
    "app_commands.command": "slash",
    "app_commands.hybrid_command": "slash",
    "app_commands.context_menu": "context_menu",
}


def literal(node, default=None):
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return default


def call_attr(node):
    """Return `module.attr` for a decorator/call node, or '' when it is not an attribute call."""
    func = node.func if isinstance(node, ast.Call) else node
    parts = []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
    return ".".join(reversed(parts))


def kwargs_of(node):
    if not isinstance(node, ast.Call):
        return {}
    return {kw.arg: kw.value for kw in node.keywords if kw.arg}


def loaded_modules(repo: pathlib.Path) -> tuple[set[str], set[str]]:
    """Modules the bot registers eagerly (bot.py) and lazily (load_extension). AST, not grep."""
    eager, lazy = set(), set()
    bot_py = repo / "bot.py"
    if bot_py.exists():
        tree = ast.parse(bot_py.read_text(encoding="utf-8"))
        aliases = {}
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "cogs" and node.level == 0:
                for alias in node.names:
                    aliases[alias.asname or alias.name] = alias.name
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "install" and isinstance(node.func.value, ast.Name):
                    name = aliases.get(node.func.value.id)
                    if name:
                        eager.add(f"cogs.{name}")
    for path in (repo / "angel" / "client.py", repo / "bot.py"):
        if not path.exists():
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if re.fullmatch(r"cogs\.[a-z_0-9]+", node.value):
                    lazy.add(node.value)
    return eager, lazy


def module_source(rel: pathlib.PurePath) -> str:
    return rel.with_suffix("").as_posix().replace("/", ".")


def collect(repo: pathlib.Path) -> dict:
    eager, lazy = loaded_modules(repo)
    loaded = eager | lazy
    commands, errors = [], []
    files = 0
    for path in sorted(repo.rglob("*.py")):
        rel = path.relative_to(repo)
        if any(part in SKIP_DIRS for part in rel.parts[:-1]):
            continue
        if rel.parts[0] != "cogs":
            continue
        files += 1
        module = module_source(rel)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = [(call_attr(d), d) for d in node.decorator_list]
            kind = next((COMMAND_DECORATORS[name] for name, _ in decorators if name in COMMAND_DECORATORS), None)
            if kind is None:
                continue
            own = next(d for name, d in decorators if name in COMMAND_DECORATORS)
            kw = kwargs_of(own)
            name = literal(kw.get("name")) or node.name.lstrip("_")
            perms: list[str] = []
            for _deco_name, deco in decorators:
                if call_attr(deco).endswith(".default_permissions") or call_attr(deco) == "has_perm_or_mistress":
                    perms.extend(k for k, v in kwargs_of(deco).items() if literal(v) is True)
            describe, choices = {}, {}
            for deco_name, deco in decorators:
                if deco_name == "app_commands.describe":
                    describe.update({k: literal(v) for k, v in kwargs_of(deco).items()})
                elif deco_name == "app_commands.choices":
                    for param, values in kwargs_of(deco).items():
                        choices[param] = [
                            literal(kwargs_of(item).get("name")) for item in getattr(values, "elts", [])
                        ]
            options = []
            args = node.args.args[1:]  # drop self
            defaults = [None] * (len(args) - len(node.args.defaults)) + list(node.args.defaults)
            for arg, default in zip(args, defaults):
                if arg.arg == "interaction":
                    continue
                ann = literal_annotation(arg.annotation)
                if ann in ("discord.Interaction",):
                    continue
                options.append({
                    "name": arg.arg,
                    "type": ann,
                    "description": describe.get(arg.arg),
                    "required": default is None,
                    "choices": [c for c in choices.get(arg.arg, []) if c],
                })
            if kind == "context_menu":
                options = []  # the target message is implicit: discord.py reports no parameters
            if module not in loaded:
                errors.append(f"{module}:{node.lineno} {name} is decorated but {module} is never installed/loaded")
            cat_id, cat_en, cat_ar = CATEGORIES.get(rel.stem, (rel.stem, rel.stem.replace("_", " ").title(), rel.stem))
            # The decorator literal is what Discord itself registers (and the oracle's truth); the
            # site's Arabic is the editorial file, which build() layers over this.
            description = literal(kw.get("description"))
            commands.append({
                "name": name,
                "kind": kind,
                "category": cat_id,
                "category_en": cat_en,
                "category_ar": cat_ar,
                "description_ar": description,
                "description_discord": description,
                "module": module,
                "config_scope": "guild" if kind == "slash" else "message",
                # Two different concepts used to share one field. `caller_gate` is what the
                # invoking member must hold (app_commands.default_permissions and the runtime
                # has_perm_or_mistress gate); `bot_permissions` is the subset of that which the bot
                # itself also holds at invite time, i.e. what the row may safely show. `administrator`
                # can only ever be a caller gate, so it never reaches the second field.
                "caller_gate": sorted(set(perms)),
                "owner_only": is_owner_only(node),
                "options": options,
                "source": f"{rel.as_posix()}:{node.lineno}",
            })
    seen = {}
    for command in commands:
        if command["name"] in seen:
            errors.append(f"duplicate command name {command['name']!r} ({command['source']} and {seen[command['name']]})")
        seen[command["name"]] = command["source"]
    commands.sort(key=lambda c: (c["category"], c["name"]))
    return {"commands": commands, "errors": errors, "files": files, "eager": eager, "lazy": lazy}


def is_mistress_denial(test: ast.AST) -> bool:
    """True for exactly `not is_mistress(...)`, the shape of an owner gate."""
    return (
        isinstance(test, ast.UnaryOp)
        and isinstance(test.op, ast.Not)
        and isinstance(test.operand, ast.Call)
        and isinstance(test.operand.func, ast.Name)
        and test.operand.func.id == "is_mistress"
    )


def is_owner_only(node: ast.AST) -> bool:
    """True when the handler refuses everyone but the owner before doing any work.

    Structural, not textual: an early owner denial whose body returns is an access gate, so the
    command is owner-only even though it also carries a Discord permission. The denial counts as a
    top-level disjunct (`if not is_mistress(u) or not interaction.guild:`), but not inside an `and`
    chain: there it protects a target from a higher-ranked caller (`kick`, `ban`, `rep`), which an
    administrator still passes.
    """
    for stmt in ast.walk(node):
        if not isinstance(stmt, ast.If):
            continue
        test = stmt.test
        teeth = test.values if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or) else [test]
        if not any(is_mistress_denial(t) for t in teeth):
            continue
        if any(isinstance(child, ast.Return) for child in ast.walk(stmt)):
            return True
    return False


def literal_annotation(node) -> str:
    if node is None:
        return "unknown"
    if isinstance(node, ast.Name):
        return node.id
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001 - unparse is best effort on exotic annotations
        return "unknown"


def totals(commands: list[dict]) -> dict:
    cats = {}
    for command in commands:
        cats[command["category"]] = cats.get(command["category"], 0) + 1
    return {
        "all": len(commands),
        "slash": sum(1 for c in commands if c["kind"] == "slash"),
        "context_menu": sum(1 for c in commands if c["kind"] == "context_menu"),
        "categories": len(cats),
        "per_category": dict(sorted(cats.items())),
    }


def invite(repo: pathlib.Path) -> dict:
    data = json.loads((HERE / "data" / "invite.json").read_text(encoding="utf-8"))
    names = [entry["permission"] for entry in data["bot_permissions"]]
    unknown = [n for n in names if n not in PERMISSION_BITS]
    if unknown:
        raise SystemExit(f"unknown permission names in data/invite.json: {unknown}")
    value = sum(1 << PERMISSION_BITS[n] for n in names)
    if "administrator" in names:
        raise SystemExit("refusing to request Administrator: it is only ever a command gate, never a bot need")
    scope = "bot%20applications.commands"
    return {
        "application_id": data["application_id"],
        "application_name": data["application_name"],
        "verified": data["verified"],
        "scope": ["bot", "applications.commands"],
        "permission_names": names,
        "permissions_value": value,
        "invite_url": f"https://discord.com/oauth2/authorize?client_id={data['application_id']}&permissions={value}&scope={scope}",
        "permissions": data["bot_permissions"],
        "notes": data.get("notes", []),
    }


RELEASE_HEADING = re.compile(r"^##\s+(\S+)\s+[—–-]\s+(\d{4}-\d{2}-\d{2})\s*$")
SECTION_HEADING = re.compile(r"^###\s+(.+?)\s*$")
BULLET = re.compile(r"^[-*]\s+(.+?)\s*$")


def parse_changelog(path: pathlib.Path) -> dict:
    """Parse `## <version> — <date>` sections with `### <topic>` bullet lists."""
    releases: dict[str, dict] = {}
    if not path.is_file():
        return releases
    current: dict | None = None
    section: str | None = None
    summary_lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        heading = RELEASE_HEADING.match(line)
        if heading:
            if current is not None:
                current["summary"] = " ".join(summary_lines).strip()
            version, date = heading.group(1), heading.group(2)
            current = {"version": version, "date": date, "summary": "", "sections": []}
            releases[version] = current
            section = None
            summary_lines = []
            continue
        if current is None:
            continue
        section_heading = SECTION_HEADING.match(line)
        if section_heading:
            section = section_heading.group(1).strip()
            current["sections"].append({"title": section, "items": []})
            continue
        bullet = BULLET.match(line)
        if bullet and section is not None:
            current["sections"][-1]["items"].append(bullet.group(1))
            continue
        if section is not None and line.strip() and current["sections"][-1]["items"]:
            # A wrapped bullet: keep it as one sentence for the site.
            current["sections"][-1]["items"][-1] += " " + line.strip()
            continue
        if section is None and line.strip() and not line.startswith("#"):
            summary_lines.append(line.strip())
    if current is not None:
        current["summary"] = " ".join(summary_lines).strip()
    return releases


def changelog(repo: pathlib.Path) -> dict:
    """Bilingual releases: English text from CHANGELOG.md, Arabic from CHANGELOG.ar.md."""
    english = parse_changelog(repo / "CHANGELOG.md")
    arabic = parse_changelog(repo / "CHANGELOG.ar.md")
    releases = []
    for version, en in english.items():
        ar = arabic.get(version, {})
        ar_sections = ar.get("sections", [])
        sections = []
        for index, en_section in enumerate(en["sections"]):
            ar_section = ar_sections[index] if index < len(ar_sections) else {}
            ar_items = ar_section.get("items", [])
            sections.append({
                "title": {"en": en_section["title"], "ar": ar_section.get("title") or en_section["title"]},
                "items": [
                    {"en": item, "ar": ar_items[i] if i < len(ar_items) else item}
                    for i, item in enumerate(en_section["items"])
                ],
            })
        releases.append({
            "version": version,
            "date": en["date"],
            "summary": {"en": en["summary"], "ar": ar.get("summary") or en["summary"]},
            "sections": sections,
        })
    releases.sort(key=lambda release: release["date"], reverse=True)
    return {
        "schema": 1,
        "source": ["CHANGELOG.md", "CHANGELOG.ar.md"],
        "releases": releases,
    }


def site_facts(repo: pathlib.Path, release_data: dict) -> dict:
    """Project facts the site may publish, derived from the checked-out tree."""
    version_match = re.search(
        r'^__version__\s*=\s*["\']([^"\']+)["\']',
        (repo / "angel" / "__init__.py").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if not version_match:
        raise SystemExit("angel/__init__.py has no __version__")
    media_platforms = count_media_platforms(repo)
    releases = release_data["releases"]
    latest = releases[0] if releases else None
    return {
        "schema": 1,
        "version": version_match.group(1),
        "license": "MIT",
        "license_url": "https://github.com/Certainty7/angelbot/blob/master/LICENSE",
        "repository": "https://github.com/Certainty7/angelbot",
        "release_url": "https://github.com/Certainty7/angelbot/releases",
        "default_branch": "master",
        "media_platforms": media_platforms,
        "latest_release": (
            {
                "version": latest["version"],
                "date": latest["date"],
                "summary": latest["summary"],
            }
            if latest else None
        ),
    }


def build(repo: pathlib.Path) -> tuple[dict, dict]:
    found = collect(repo)
    if found["errors"]:
        raise SystemExit("catalogue generation refused:\n  " + "\n  ".join(found["errors"]))
    commands = found["commands"]
    en = json.loads((HERE / "data" / "descriptions_en.json").read_text(encoding="utf-8"))
    ar_extra = json.loads((HERE / "data" / "descriptions_ar.json").read_text(encoding="utf-8"))
    missing_en = [c["name"] for c in commands if not en.get(c["name"])]
    for command in commands:
        command["description_en"] = en.get(command["name"])
        # The editorial file is the site's Arabic source; the decorator literal is only the fallback
        # for a command it does not cover (the 3 context menus, which Discord gives no description).
        command["description_ar"] = ar_extra.get(command["name"]) or command["description_ar"]
    invite_names = {entry["permission"] for entry in json.loads(
        (HERE / "data" / "invite.json").read_text(encoding="utf-8"))["bot_permissions"]}
    for command in commands:
        command["bot_permissions"] = [p for p in command["caller_gate"] if p in invite_names]

    counts = totals(commands)
    counts["eager"] = sum(1 for c in commands if c["module"] in found["eager"])
    counts["lazy"] = sum(1 for c in commands if c["module"] in found["lazy"])
    counts["loaded_modules"] = len(found["eager"] | found["lazy"])
    catalogue = {
        "schema": 1,
        "generator": "tools/website-data-generator/generate.py",
        "repository": "Certainty7/angelbot",
        "source_files": found["files"],
        "totals": counts,
        "missing_english_descriptions": missing_en,
        "commands": commands,
    }
    return catalogue, invite(repo)


def public_catalogue(catalogue: dict) -> dict:
    """The subset the website publishes.

    Internal structure is not product information: the repository name, the module a command lives
    in and the source line that defines it stay in the tool's own data. Publishing file paths and
    module names is exactly what the content policy forbids, and the site has no use for them.
    """
    public = {key: value for key, value in catalogue.items() if key != "repository"}
    public["commands"] = [
        {key: value for key, value in command.items() if key not in ("module", "source")}
        for command in catalogue["commands"]
    ]
    return public


def public_invite(invite_data: dict) -> dict:
    """Drop the per-permission code references; keep what a visitor needs to understand the ask."""
    return {
        "application_id": invite_data["application_id"],
        "application_name": invite_data["application_name"],
        "scope": invite_data["scope"],
        "permission_names": invite_data["permission_names"],
        "permissions_value": invite_data["permissions_value"],
        "invite_url": invite_data["invite_url"],
        "permissions": [
            {"permission": entry["permission"], "why": entry["why"]}
            for entry in invite_data["permissions"]
        ],
        "notes": invite_data["notes"],
    }


_PLATFORM_HOSTS = (
    ("instagram", ("instagram.com", "instagr.am")),
    ("tiktok", ("tiktok.com",)),
    ("x", ("x.com", "twitter.com")),
    ("reddit", ("reddit.com", "redd.it")),
)


def count_media_platforms(repo: pathlib.Path) -> int:
    """Distinct platforms covered by the gallery fixtures.

    Counting `*.case.json` files published 14 "platforms" for four sites: the fixtures are
    one file per scenario, not per platform (C-033).
    """
    families = set()
    for path in (repo / "tests" / "fixtures" / "gallery").glob("*.case.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        host = (urlparse(data.get("url", "")).hostname or "").lower()
        for name, hosts in _PLATFORM_HOSTS:
            if any(host == h or host.endswith("." + h) for h in hosts):
                families.add(name)
                break
    if not families:
        raise SystemExit("gallery fixtures name no known media platform")
    return len(families)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(REPO), type=pathlib.Path)
    parser.add_argument("--out", default=None, type=pathlib.Path)
    parser.add_argument("--check", action="store_true", help="exit 1 when the output is stale")
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args(argv)

    repo = args.repo_root.resolve()
    out = args.out or (repo / "website" / "src" / "data")
    catalogue, invite_data = build(repo)
    release_data = changelog(repo)
    facts = site_facts(repo, release_data)
    payloads = {
        out / "commands.json": public_catalogue(catalogue),
        out / "invite.json": public_invite(invite_data),
        out / "changelog.json": release_data,
        out / "site.json": facts,
    }
    stale = []
    for path, payload in payloads.items():
        text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(str(path))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    if args.check and stale:
        print("stale generated data (run the generator and commit): " + ", ".join(stale), file=sys.stderr)
        return 1
    if args.print_summary or not args.check:
        counts = catalogue["totals"]
        print(f"commands: {counts['all']} (slash {counts['slash']}, context menus {counts['context_menu']}) "
              f"| eager {counts['eager']} + lazy {counts['lazy']} | categories {counts['categories']}")
        print(f"invite: {invite_data['invite_url']}  mask={invite_data['permissions_value']}")
        print(f"missing English descriptions: {len(catalogue['missing_english_descriptions'])}")
        print(f"version: {facts['version']} | releases: {len(release_data['releases'])} | "
              f"media platforms: {facts['media_platforms']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
