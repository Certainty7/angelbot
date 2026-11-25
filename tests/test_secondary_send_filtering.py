"""Audit finding 18: every send path must apply the same output filtering and mention policy.

Two secondary paths bypassed it. The autonomy engine interpolated model text straight into a
message whose AllowedMentions allowed *any* user mention, so a fabricated `<@id>` in the model
output pinged a foreign member under the bot's identity. Music notices rendered YouTube titles
with the default mention policy, so a title shaped like `<@id>` pinged too.

The invariant: model text and third-party titles never carry an active mention, while the
autonomy target is still mentioned exactly once.
"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from angel import autonomy


def _ids(allowed):
    return sorted(m.id for m in (allowed.users or []))


class AmbientPayloadTest(unittest.TestCase):
    def test_a_foreign_member_mention_is_neutralised(self):
        body, allowed = autonomy.build_ambient_payload(7, "هلا <@999> شخبارك؟")
        self.assertNotIn("<@999>", body)
        self.assertTrue(body.startswith("<@7> "))
        self.assertEqual(_ids(allowed), [7])
        self.assertFalse(allowed.everyone)
        self.assertFalse(allowed.roles)

    def test_a_role_and_mass_mention_are_neutralised(self):
        body, allowed = autonomy.build_ambient_payload(7, "يا <@&88> و@everyone")
        self.assertNotIn("<@&88>", body)
        self.assertNotIn("@everyone", body)
        self.assertEqual(_ids(allowed), [7])

    def test_a_secret_shape_is_redacted(self):
        body, _ = autonomy.build_ambient_payload(7, "خذ sk-" + "a" * 30)
        self.assertNotIn("sk-" + "a" * 30, body)

    def test_the_target_is_mentioned_exactly_once(self):
        body, _ = autonomy.build_ambient_payload(7, "مرحبا <@7>")
        self.assertEqual(body.count("<@7>"), 1)


class MusicNoticeTest(unittest.TestCase):
    def _cog(self, skipped, nxt):
        from cogs.music import Music

        cog = object.__new__(Music)
        cog.bot = MagicMock()
        cog.engine = MagicMock()
        cog.engine.skip = AsyncMock(return_value=skipped)
        cog.engine.state = MagicMock(
            return_value=SimpleNamespace(current=nxt, tracks=[])
        )
        cog._require_voice = AsyncMock(return_value=SimpleNamespace(id=11, mention="#v"))
        return cog

    def _run_skip(self, cog):
        from cogs.music import Music

        interaction = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.guild.voice_client = SimpleNamespace(
            channel=SimpleNamespace(id=11, mention="#v")
        )
        asyncio.run(Music.skip.callback(cog, interaction))
        return interaction

    def test_a_skip_notice_disables_mentions(self):
        skipped = SimpleNamespace(title="<@999> song")
        cog = self._cog(skipped, None)
        interaction = self._run_skip(cog)
        kwargs = interaction.followup.send.await_args.kwargs
        self.assertIn("allowed_mentions", kwargs)
        self.assertFalse(kwargs["allowed_mentions"].everyone)
        self.assertFalse(kwargs["allowed_mentions"].users)

    def test_skip_to_next_disables_mentions(self):
        skipped = SimpleNamespace(title="<@999> one")
        nxt = SimpleNamespace(title="<@&88> two")
        cog = self._cog(skipped, nxt)
        interaction = self._run_skip(cog)
        kwargs = interaction.followup.send.await_args.kwargs
        self.assertIn("allowed_mentions", kwargs)
        self.assertFalse(kwargs["allowed_mentions"].everyone)


if __name__ == "__main__":
    unittest.main()
