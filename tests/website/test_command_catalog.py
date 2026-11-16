#!/usr/bin/env python3
"""Offline checks for the generated website data.

The website publishes numbers, so the numbers need an oracle. `fixtures/runtime_census.json` was
captured from the live tree by importing each cog's `install()` against a stub command tree: it is
what Discord actually receives, not what a decorator search believes. The generated catalogue must
agree with it entry by entry, and the invite link must be rebuilt from first principles here rather
than trusted.

Run: python3 tests/website/test_command_catalog.py
"""
import importlib.util
import json
import pathlib
import subprocess
import sys
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
GENERATOR = REPO / "tools" / "website-data-generator" / "generate.py"
DATA = REPO / "website" / "src" / "data"
FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "runtime_census.json"
AR_SOURCE = REPO / "tools" / "website-data-generator" / "data" / "descriptions_ar.json"
INVITE_SOURCE = REPO / "tools" / "website-data-generator" / "data" / "invite.json"

# The ten commands whose handler refuses everyone but the owner (docs/COMMANDS.md, grounded in the
# source's `is_mistress` gates). Hand-written on purpose: this is the oracle, not a copy of the
# generator's own answer.
OWNER_ONLY = {
    "sync", "diagnostics", "mood", "autonomy", "silence",
    "harem", "sovereign", "dm_send", "whisper", "dm_logs",
}


def load_generator():
    spec = importlib.util.spec_from_file_location("website_data_generator", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CatalogueTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gen = load_generator()
        cls.catalogue = json.loads((DATA / "commands.json").read_text(encoding="utf-8"))
        cls.invite = json.loads((DATA / "invite.json").read_text(encoding="utf-8"))
        cls.census = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.full = {c["name"]: c for c in cls.gen.collect(REPO)["commands"]}
        cls.invite_source = json.loads(INVITE_SOURCE.read_text(encoding="utf-8"))
        cls.by_name = {c["name"]: c for c in cls.catalogue["commands"]}

    def test_totals_are_internally_consistent(self):
        totals = self.catalogue["totals"]
        self.assertEqual(totals["all"], len(self.catalogue["commands"]))
        self.assertEqual(totals["slash"] + totals["context_menu"], totals["all"])
        self.assertEqual(sum(totals["per_category"].values()), totals["all"])
        self.assertEqual(totals["eager"] + totals["lazy"], totals["all"])
        self.assertEqual(totals["eager"], self.census["global_commands"])
        self.assertEqual(totals["categories"], len(totals["per_category"]))

    def test_every_runtime_command_is_present_and_identical(self):
        for runtime in self.census["commands"]:
            with self.subTest(command=runtime["name"]):
                generated = self.by_name.get(runtime["name"])
                self.assertIsNotNone(generated, "runtime command missing from the catalogue")
                if runtime["description"] is not None:  # context menus carry no description in Discord
                    self.assertEqual(generated["description_discord"], runtime["description"])
                self.assertEqual(self.full[runtime["name"]]["module"], runtime["module"])
                self.assertEqual(sorted(generated["caller_gate"]), sorted(runtime["default_permissions"]))
                self.assertEqual([o["name"] for o in generated["options"]], runtime["options"])
                self.assertEqual(generated["kind"], "context_menu" if runtime["type"] == "ContextMenu" else "slash")

    def test_lazy_music_commands_are_present(self):
        music = {name for name, command in self.full.items() if command["module"] == "cogs.music"}
        self.assertEqual(music, {"play", "skip", "queue", "playlist"})
        for name in music:
            self.assertNotIn(name, {c["name"] for c in self.census["commands"]}, "music must stay lazy, not eager")

    def test_names_are_unique_and_documented(self):
        names = [c["name"] for c in self.catalogue["commands"]]
        self.assertEqual(len(names), len(set(names)))
        for command in self.catalogue["commands"]:
            with self.subTest(command=command["name"]):
                self.assertTrue((command["description_ar"] or "").strip())
                self.assertTrue((command["description_en"] or "").strip())
                self.assertTrue(command["category_en"] and command["category_ar"])
        self.assertEqual(self.catalogue["missing_english_descriptions"], [])

    def test_arabic_copy_comes_from_the_editorial_file(self):
        ar = json.loads(AR_SOURCE.read_text(encoding="utf-8"))
        for name, text in ar.items():
            with self.subTest(command=name):
                self.assertEqual(self.by_name[name]["description_ar"], text)

    def test_owner_only_matches_the_source_gates(self):
        actual = {c["name"] for c in self.catalogue["commands"] if c["owner_only"]}
        self.assertEqual(actual, OWNER_ONLY)

    def test_invite_mask_is_recomputed_not_copied(self):
        names = self.invite["permission_names"]
        self.assertEqual(len(names), len(set(names)), "duplicate permission entries")
        expected = sum(1 << self.gen.PERMISSION_BITS[n] for n in names)
        self.assertEqual(self.invite["permissions_value"], expected)
        self.assertNotIn("administrator", names)
        self.assertEqual(
            self.invite["invite_url"],
            "https://discord.com/oauth2/authorize?client_id={}&permissions={}&scope=bot%20applications.commands".format(
                self.invite["application_id"], expected
            ),
        )
        for entry in self.invite_source["bot_permissions"]:
            self.assertIn(entry["permission"], names)
            self.assertTrue(entry["why"] and entry["evidence"])
        published = {entry["permission"]: entry for entry in self.invite["permissions"]}
        self.assertEqual(set(published), set(names))
        for entry in published.values():
            self.assertEqual(set(entry), {"permission", "why"})

    def test_administrator_is_a_caller_gate_only(self):
        # `administrator` is what a member may hold; it is never something the bot asks for, so it
        # must not reach the field the rows render.
        for command in self.catalogue["commands"]:
            with self.subTest(command=command["name"]):
                self.assertNotIn("administrator", command["bot_permissions"])
                self.assertTrue(set(command["bot_permissions"]).issubset(set(command["caller_gate"])))
        gated = {c["name"] for c in self.catalogue["commands"] if "administrator" in c["caller_gate"]}
        self.assertTrue({"set_modlog", "custom_action"} <= gated)
        for name in ("set_modlog", "custom_action"):
            self.assertEqual(self.by_name[name]["bot_permissions"], [])

    def test_public_data_carries_no_internal_paths(self):
        published = (DATA / "commands.json").read_text(encoding="utf-8") + (DATA / "invite.json").read_text(encoding="utf-8")
        for marker in ("cogs/", "angel/", ".py:", "/home/", "Certainty7", "evidence", "\"module\"", "\"source\""):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, published)
        for command in self.catalogue["commands"]:
            self.assertEqual(
                set(command),
                {"name", "kind", "category", "category_en", "category_ar", "description_ar",
                 "description_discord", "config_scope", "caller_gate", "bot_permissions", "owner_only",
                 "options", "description_en"},
            )

    def test_generated_files_are_fresh(self):
        result = subprocess.run(
            [sys.executable, str(GENERATOR), "--check"],
            cwd=REPO, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
