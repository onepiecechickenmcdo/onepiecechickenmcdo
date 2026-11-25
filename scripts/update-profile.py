"""Refresh the airport profile from GitHub's public contribution records."""

from collections import Counter
from datetime import datetime, time, timedelta, timezone
from html import escape
import json
from pathlib import Path
import re
import subprocess
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
LOGIN = "onepiecechickenmcdo"
MANILA = timezone(timedelta(hours=8))
OMIT = {f"{LOGIN}/{name}" for name in (LOGIN, "activity-sandbox", "ebangka")}
SVG = "http://www.w3.org/2000/svg"
REPOSITORY = "nameWithOwner isPrivate"
ACTIVITY = {
    "commits": ("commit", "commits"),
    "pulls": ("pull request", "pull requests"),
    "issues": ("issue", "issues"),
    "reviews": ("review", "reviews"),
}
EVENTS = {
    "pulls": ("pullRequestContributions", f"pullRequest {{ repository {{ {REPOSITORY} }} }}"),
    "issues": ("issueContributions", f"issue {{ repository {{ {REPOSITORY} }} }}"),
    "reviews": ("pullRequestReviewContributions", f"repository {{ {REPOSITORY} }}"),
}


def github(fields, declaration="", arguments=None):
    query = f"query($login: String!{declaration}) {{ user(login: $login) {{ {fields} }} }}"
    response = subprocess.run(
        ["gh", "api", "graphql", "--input", "-"],
        input=json.dumps({"query": query, "variables": {"login": LOGIN, **(arguments or {})}}),
        capture_output=True, encoding="utf-8", check=True,
    )
    payload = json.loads(response.stdout)
    if payload.get("errors") or not payload.get("data", {}).get("user"):
        raise RuntimeError(f"GitHub did not return public profile data: {payload.get('errors')}")
    return payload["data"]["user"]


def public(repository):
    return not repository["isPrivate"] and repository["nameWithOwner"].casefold() not in OMIT


def activity(first, now):
    collection = "contributionsCollection(from: $first, to: $end)"
    args = {"first": datetime.combine(first, time.min, MANILA).isoformat(), "end": now.isoformat()}
    dates = ", $first: DateTime!, $end: DateTime!"
    events = " ".join(
        f"{key}: {field}(first: 100) {{ nodes {{ occurredAt {fields} }} pageInfo {{ hasNextPage endCursor }} }}"
        for key, (field, fields) in EVENTS.items()
    )
    data = github(f"""{collection} {{
        totalRepositoriesWithContributedCommits
        commitContributionsByRepository(maxRepositories: 100) {{
            repository {{ {REPOSITORY} }}
            contributions(first: 100) {{ nodes {{ occurredAt commitCount }} }}
        }}
        {events}
    }}""", dates, args)["contributionsCollection"]
    commits = data["commitContributionsByRepository"]
    if len(commits) < data["totalRepositoriesWithContributedCommits"] and len(commits) == 100:
        raise RuntimeError("GitHub's 100-repository commit limit was reached; the published chart was kept.")

    weeks = [0] * 12
    totals = Counter()

    def add(kind, entries, repository):
        for entry in entries:
            occurred = datetime.fromisoformat(entry["occurredAt"]).astimezone(MANILA).date()
            day = (occurred - first).days
            if 0 <= day < 84 and public(repository(entry)):
                count = entry.get("commitCount", 1)
                totals[kind] += count
                weeks[day // 7] += count

    for repo in commits:
        add("commits", repo["contributions"]["nodes"], lambda entry: repo["repository"])
    for kind, (field, fields) in EVENTS.items():
        connection = data[kind]
        while True:
            add(kind, connection["nodes"], lambda entry: (
                entry.get("pullRequest") or entry.get("issue") or entry
            )["repository"])
            page = connection["pageInfo"]
            if not page["hasNextPage"]:
                break
            connection = github(f"""{collection} {{
                {field}(first: 100, after: $cursor) {{
                    nodes {{ occurredAt {fields} }} pageInfo {{ hasNextPage endCursor }}
                }}
            }}""", dates + ", $cursor: String!", {**args, "cursor": page["endCursor"]})["contributionsCollection"][field]
    return weeks, totals


def projects():
    repos = github("""repositories(first: 100, ownerAffiliations: [OWNER], privacy: PUBLIC, isFork: false,
        orderBy: {field: CREATED_AT, direction: DESC}) {
        nodes { name nameWithOwner description isPrivate isArchived }
    }""")["repositories"]["nodes"]
    eligible = [repo for repo in repos if public(repo) and not repo["isArchived"]]
    pokefolio = next((repo for repo in eligible if re.fullmatch(r"poke[-_]?folio", repo["name"], re.I)), None)
    return [repo for repo in eligible if repo != pokefolio][:3], pokefolio


def render_svg(path, repos):
    ET.register_namespace("", SVG)
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    root = ET.parse(path, parser=parser).getroot()
    elements = {node.get("id"): node for node in root.iter() if node.get("id")}
    shift = 53 * len(repos)
    root.set("viewBox", f"0 0 1200 {1106 + shift}")
    root.set("height", str(1106 + shift))
    elements["background"].set("height", str(1106 + shift))
    for name in ("projects-clip", "projects-paper", "projects-grain"):
        elements[name].set("height", str(365 + shift))
    elements["route-map"].set("transform", f"translate(0 {shift})")
    board = elements["recent-projects"]
    for child in list(board):
        board.remove(child)
    for index, repo in enumerate(repos):
        y = 797 + 53 * index
        ET.SubElement(board, f"{{{SVG}}}path", {"d": f"M100 {y - 37}h1000", "stroke": "#d3c9b7"})
        title = ET.SubElement(board, f"{{{SVG}}}text", {"x": "100", "y": str(y), "font-weight": "700"})
        title.text = shorten(repo["name"], 23)
        label = ET.SubElement(board, f"{{{SVG}}}text", {"x": "395", "y": str(y)})
        label.text = shorten(repo["description"] or "Public repository", 54)
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode") + "\n"


def shorten(value, limit):
    value = " ".join(value.split())
    return value if len(value) <= limit else value[:limit - 1].rstrip() + "…"


def markdown_text(value):
    return re.sub(r"([\\`*_[\]~|!])", r"\\\1", escape(" ".join(value.split()), quote=False))


def render_readme(text, repos, pokefolio, first, last, weeks, totals):
    def insert(name, content):
        return re.sub(
            rf"(<!-- BEGIN:{name} -->\n).*?(<!-- END:{name} -->)",
            lambda match: match[1] + content + match[2],
            text, count=1, flags=re.S,
        )

    lines = []
    for repo in repos:
        name = markdown_text(repo["name"])
        description = repo["description"]
        line = f'- [**{name}**](https://github.com/{repo["nameWithOwner"]})'
        lines.append(line + (f" · {markdown_text(description)}" if description else ""))
    text = insert("recent-projects", ("\n" + "\n".join(lines) + "\n\n") if lines else "")

    def poke_link(match):
        title = "**Pokéfolio**"
        if pokefolio:
            title = f'[{title}](https://github.com/{pokefolio["nameWithOwner"]})'
        return "- " + title + match[1]

    text = re.sub(
        r"^- (?:\[\*\*Pokéfolio\*\*\]\(https://github\.com/[^)]+\)|\*\*Pokéfolio\*\*)( · .*)$",
        poke_link, text, count=1, flags=re.M,
    )
    labels = [f"{totals[key]} {names[totals[key] != 1]}" for key, names in ACTIVITY.items() if totals[key]]
    summary = ", ".join(labels[:-1]) + (" and " if len(labels) > 1 else "") + (labels[-1] if labels else "0 contributions")
    start = f"{first:%b} {first.day}" + (f", {first.year}" if first.year != last.year else "")
    end = f"{last:%b} {last.day}, {last.year}"
    rows = "\n".join(
        f"| {day:%b} {day.day} | {count} |"
        for index, count in enumerate(weeks)
        for day in (first + timedelta(weeks=index),)
    )
    return insert("activity", f"""**Public activity, {start}–{end}** · {summary}.

<details>
<summary>Weekly contribution counts</summary>

| Week starting | Contributions |
| --- | ---: |
{rows}

</details>
""")


def main():
    now = datetime.now(MANILA)
    last = now.date()
    first = last - timedelta(days=83)
    weeks, totals = activity(first, now)
    repos, pokefolio = projects()
    image = ROOT / "assets/airport-profile.svg"
    readme = ROOT / "README.md"
    updated_svg = render_svg(image, repos)
    updated_readme = render_readme(readme.read_text(encoding="utf-8"), repos, pokefolio, first, last, weeks, totals)
    image.write_text(updated_svg, encoding="utf-8", newline="\n")
    readme.write_text(updated_readme, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
