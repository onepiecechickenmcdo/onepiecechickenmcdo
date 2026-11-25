"""Check the layout and text produced when a new public project appears."""

from collections import Counter
from datetime import date
from pathlib import Path
import runpy
from xml.etree import ElementTree


scripts = Path(__file__).resolve().parent
profile = runpy.run_path(str(scripts / "update-profile.py"))
root = scripts.parent
repos = [{"name": "new_project", "nameWithOwner": "example/new_project", "description": "Research < tools"}]
pokefolio = {"nameWithOwner": "example/pokefolio"}
first, last = date(2026, 9, 4), date(2026, 11, 26)
weeks = [1, *([0] * 10), 20]

svg = ElementTree.fromstring(profile["render_svg"](root / "assets/airport-profile.svg", repos))
nodes = {node.get("id"): node for node in svg.iter() if node.get("id")}
assert svg.get("viewBox") == "0 0 1200 1159"
assert nodes["route-map"].get("transform") == "translate(0 53)"
projects = nodes["projects-clip"]
route = nodes["route-card"][0]
assert int(route.get("y")) + 53 - (int(projects.get("y")) + int(projects.get("height"))) == 22
assert nodes["route-map"].get("clip-path") == "url(#route-card)"
assert "20th in the Bifrost track" in list(nodes["route-map"].itertext())
assert "Research < tools" in list(nodes["recent-projects"].itertext())

readme = (root / "README.md").read_text(encoding="utf-8")
generate = profile["render_readme"]
counts = Counter({"commits": 20, "reviews": 1})
updated = generate(readme, repos, pokefolio, first, last, weeks, counts)
assert "https://github.com/example/pokefolio" in updated
assert "Research &lt; tools" in updated
assert "20 commits and 1 review." in updated
assert updated == generate(updated, repos, pokefolio, first, last, weeks, counts)
assert "https://github.com/example/pokefolio" not in generate(updated, [], None, first, last, weeks, counts)
