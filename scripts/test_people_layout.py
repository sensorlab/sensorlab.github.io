"""Run with `python3 -m unittest discover -s scripts -p test_people_layout.py` (requires Hugo)."""

import json
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PeopleLayoutTest(unittest.TestCase):
    def test_people_cards_and_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            shutil.copytree(ROOT / "layouts/people", site / "layouts/people")
            shutil.copytree(ROOT / "layouts/partials/people", site / "layouts/partials/people")
            (site / "layouts/_default").mkdir()
            (site / "layouts/_default/baseof.html").write_text('{{ block "main" . }}{{ end }}')
            (site / "assets/images").mkdir(parents=True)
            shutil.copyfile(ROOT / "assets/images/unk.png", site / "assets/images/unk.png")
            config = tomllib.loads((ROOT / "hugo.toml").read_text())
            (site / "hugo.json").write_text(
                json.dumps(
                    {
                        "baseURL": "https://example.org/",
                        "permalinks": config["permalinks"],
                    }
                )
            )
            people = site / "content/people"
            people.mkdir(parents=True)
            (people / "_index.md").write_text("---\ntitle: People\n---\n")
            # Deliberately conflicting tags: placement must depend on the folder.
            for group, username, title, position, tag in [
                ("active", "alice", "Alice Active", 10, "alumni"),
                ("active", "bob", "Bob Active", 20, "researchers"),
                ("alumni", "carol", "Carol Former", 10, "researchers"),
                ("alumni", "dave", "Dave Former", 20, "alumni"),
                ("active", "eva", "Eva Active", 0, "researchers"),
                ("active", "frank", "Frank Active", 0, "researchers"),
            ]:
                bundle = people / group / username
                bundle.mkdir(parents=True)
                role_fields = {
                    "alice": 'role: "Research Fellow"\nroles: []\n',
                    "bob": 'role: "Ignored Legacy Role"\nroles: ["Group Lead", "Infrastructure Coordinator"]\n',
                    "carol": 'role: ["Former Researcher", "Visiting Lecturer"]\n',
                    "dave": "role: []\n",
                    "eva": 'role: ["Software Engineer", "Systems Administrator"]\n',
                    "frank": "",
                }[username]
                (bundle / "index.md").write_text(
                    f"---\ntitle: {title}\nposition: {position}\nuser_groups: [{tag}]\n{role_fields}---\n"
                )
            build = subprocess.run(
                ["hugo", "--source", str(site), "--logLevel", "error"], capture_output=True, text=True
            )
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
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
            self.assertIn("Research Fellow", members)
            self.assertIn("Group Lead", members)
            self.assertIn("Software Engineer", members)
            self.assertNotIn("Infrastructure Coordinator", members)
            self.assertNotIn("Systems Administrator", members)
            self.assertNotIn("Ignored Legacy Role", listing)
            expected_roles = {
                "alice": ["Research Fellow"],
                "bob": ["Group Lead", "Infrastructure Coordinator"],
                "carol": ["Former Researcher", "Visiting Lecturer"],
                "dave": [],
                "eva": ["Software Engineer", "Systems Administrator"],
                "frank": [],
            }
            for username, roles in expected_roles.items():
                self.assertIn(f"https://example.org/people/{username}/", listing)
                profile = (site / f"public/people/{username}/index.html").read_text()
                self.assertIn('href="/people/"', profile)
                self.assertNotIn("Ignored Legacy Role", profile)
                for role in roles:
                    self.assertIn(role, profile)
                if len(roles) > 1:
                    self.assertLess(profile.index(roles[0]), profile.index(roles[1]))
                if not roles:
                    self.assertNotIn("<strong>Role:", profile)
                    self.assertNotIn("<strong>Roles:", profile)


if __name__ == "__main__":
    unittest.main()
