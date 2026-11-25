"""MD5 is used here to fingerprint downloaded bytes, never to prove anything.

`usedforsecurity=False` says so in the one place a reader looks: the call itself.
Bandit flags a bare `hashlib.md5(...)` as a high-severity weak hash, and a scanner
that cries wolf gets switched off. This gate keeps the flag honest and keeps the
signal worth reading.
"""

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLAIN_MD5 = re.compile(r"hashlib\.md5\((?![^)]*usedforsecurity=False)")


def offenders(text: str) -> list[str]:
    return [m.group(0) for m in PLAIN_MD5.finditer(text)]


class CryptoHygiene(unittest.TestCase):
    def test_it_flags_a_plain_md5_call(self):
        self.assertEqual(offenders("h = hashlib.md5(data).hexdigest()"), ["hashlib.md5("])

    def test_it_accepts_the_documented_form(self):
        self.assertEqual(offenders("h = hashlib.md5(data, usedforsecurity=False).hexdigest()"), [])

    def test_no_plain_md5_in_the_bot(self):
        found = {}
        for path in (ROOT / "angel").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if offenders(text):
                found[str(path.relative_to(ROOT))] = offenders(text)
        self.assertEqual(found, {})


if __name__ == "__main__":
    unittest.main()
