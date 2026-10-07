"""Run with `python3 -m unittest discover -s scripts -p test_people_layout.py` (requires Hugo)."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PeopleLayoutTest(unittest.TestCase):
    def test_folders_control_membership_and_preserve_profile_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            shutil.copytree(ROOT / "layouts/people", site / "layouts/people")
            (site / "layouts/_default").mkdir()
            (site / "layouts/_default/baseof.html").write_text('{{ block "main" . }}{{ end }}')
            (site / "assets/images").mkdir(parents=True)
            shutil.copyfile(ROOT / "assets/images/unk.png", site / "assets/images/unk.png")
            config = tomllib.loads((ROOT / "hugo.toml").read_text())
            (site / "hugo.json").write_text(json.dumps({
                "baseURL": "https://example.org/",
                "permalinks": config["permalinks"],
            }))
            people = site / "content/people"
            people.mkdir(parents=True)
            (people / "_index.md").write_text('---\ntitle: People\n---\n')
            # Deliberately conflicting tags: placement must depend on the folder.
            for group, username, title, position, tag in [
                ("active", "alice", "Alice Active", 10, "alumni"),
                ("active", "bob", "Bob Active", 20, "researchers"),
                ("alumni", "carol", "Carol Former", 10, "researchers"),
                ("alumni", "dave", "Dave Former", 20, "alumni"),
            ]:
                bundle = people / group / username
                bundle.mkdir(parents=True)
                (bundle / "index.md").write_text(
                    f'---\ntitle: {title}\nposition: {position}\nuser_groups: [{tag}]\n---\n'
                )
            subprocess.run(["hugo", "--source", str(site), "--quiet"], check=True)
            listing = (site / "public/people/index.html").read_text()
            members, alumni = listing.split("<h1>Alumni</h1>")
            self.assertIn("Alice Active", members)
            self.assertIn("Bob Active", members)
            self.assertNotIn("Carol Former", members)
            self.assertNotIn("Dave Former", members)
            self.assertLess(members.index("Bob Active"), members.index("Alice Active"))
            self.assertIn("Carol Former", alumni)
            self.assertIn("Dave Former", alumni)
            self.assertNotIn("Alice Active", alumni)
            self.assertNotIn("Bob Active", alumni)
            self.assertLess(alumni.index("Carol Former"), alumni.index("Dave Former"))
            for username in ("alice", "bob", "carol", "dave"):
                self.assertIn(f'https://example.org/people/{username}/', listing)
                profile = (site / f"public/people/{username}/index.html").read_text()
                self.assertIn('href="/people/"', profile)


if __name__ == "__main__":
    unittest.main()
