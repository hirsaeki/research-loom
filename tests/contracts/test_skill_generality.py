"""Writer and Publication skills stay generic (#506).

Organization-specific review groups, check IDs and Profile versions belong in the
delivered Profile resources. What hosts still need about one organization's Profile
lives in a clearly labelled example file, ``references/misco-profile.md``; every
other skill file must not name MISCO or pin a ``@x.y.z`` version.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS = (ROOT / "skills/writer", ROOT / "skills/publication")
EXAMPLE = "misco-profile.md"
PINNED_VERSION = re.compile(r"@\d+\.\d+\.\d+")


def specific_mentions(path: Path) -> list[str]:
    found = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        text = line.replace(f"references/{EXAMPLE}", "")
        if "misco" in text.lower() or PINNED_VERSION.search(text):
            found.append(f"{path.relative_to(ROOT).as_posix()}:{number}")
    return found


class SkillGeneralityTests(unittest.TestCase):
    def test_skills_name_no_organization_or_pinned_version_outside_the_example(self):
        found = [
            mention
            for skill in SKILLS
            for path in sorted(skill.rglob("*.md"))
            if path.name != EXAMPLE
            for mention in specific_mentions(path)
        ]
        self.assertEqual([], found, f"move organization-specific detail to references/{EXAMPLE}")

    def test_each_skill_links_its_labelled_example(self):
        for skill in SKILLS:
            with self.subTest(skill=skill.name):
                example = skill / "references" / EXAMPLE
                self.assertIn("is an example", example.read_text(encoding="utf-8"))
                self.assertIn(
                    f"references/{EXAMPLE}", (skill / "SKILL.md").read_text(encoding="utf-8")
                )


if __name__ == "__main__":
    unittest.main()
