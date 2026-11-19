"""Regression tests for the outgoing-reply sanitiser.

The v1.0.1 release passed a raw replacement template containing ``\\u200b`` to
``re.sub``, which Python's ``re`` rejects with ``bad escape \\u``. The exception
escaped ``handle_conversation`` and the generic handler answered every message
with the "unexpected error" notice, so these tests pin the plain path as well as
the two mention cases.
"""
import unittest

from angel.persona import humanize_reply


class TestHumanizeReply(unittest.TestCase):
    def test_plain_arabic_reply_survives(self):
        self.assertEqual(humanize_reply("كيف حالك اليوم؟"), "كيف حالك اليوم؟")

    def test_everyone_and_here_are_neutralised(self):
        for raw in ("يا جماعة @everyone تعالوا", "تنبيه @here فقط"):
            out = humanize_reply(raw)
            self.assertNotIn("@everyone", out)
            self.assertNotIn("@here", out)
            self.assertIn("\u200b", out)

    def test_role_mention_is_neutralised(self):
        out = humanize_reply("راجعوا <@&123456789012345678>")
        self.assertNotIn("<@&", out)
        self.assertIn("@\u200brole", out)

    def test_length_cap_keeps_a_single_ellipsis(self):
        out = humanize_reply("ا" * 2500, max_len=100)
        self.assertEqual(len(out), 100)
        self.assertTrue(out.endswith("…"))


if __name__ == "__main__":
    unittest.main()
