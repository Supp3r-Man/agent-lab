"""Render a ranked result as plain text, Markdown and HTML.

Repository names, descriptions and URLs come from GitHub and are untrusted, so the HTML escapes
everything and only links to https://github.com/ addresses.
"""

import html

GITHUB_PREFIX = "https://github.com/"


def _safe_url(url):
    return url if isinstance(url, str) and url.startswith(GITHUB_PREFIX) and " " not in url and "\n" not in url else ""


def _headline(brief):
    t = brief["totals"]
    return f"{t['repos']} repos | {t['stars']} stars | {t['forks']} forks | {t['open_issues']} open issues"


def _title(brief):
    return f"Repo Pulse for {', '.join(brief['accounts'])} - {brief['generated_at'][:10]}"


def _sections(brief):
    """A list of (heading, [entry]) where an entry is (title, detail_lines, url)."""
    sections = []
    if brief["first_run"]:
        sections.append(("First run: nothing to compare with yet. Top repos now", [
            (f"{r['name']}  ({r['stars']} stars, {r['forks']} forks)", [r["description"]] if r["description"] else [], r["url"])
            for r in brief["overview"]
        ]))
    else:
        attention = [i for i in brief["items"] if i["next_action"]]
        gains = [i for i in brief["items"] if not i["next_action"]]
        if attention:
            sections.append(("Needs attention", [(f"{i['name']}  (score {i['score']})", [", ".join(i["reasons"]), "Next: " + i["next_action"]], i["url"]) for i in attention]))
        if gains:
            sections.append(("What changed", [(f"{i['name']}  (score {i['score']})", [", ".join(i["reasons"])], i["url"]) for i in gains]))
        if brief["more"]:
            sections.append(("", [(f"...and {brief['more']} more repos with changes", [], "")]))
        if not brief["items"]:
            sections.append(("Nothing changed", [("No new stars, forks or issues since the last run.", [], "")]))
        if brief["removed"]:
            sections.append(("No longer visible", [(name, ["Deleted, renamed, made private or archived"], "") for name in brief["removed"]]))
    if brief["housekeeping"]:
        entries = [(f"{h['name']}: {', '.join(h['issues'])}", ["Next: " + "; ".join(h["actions"])], h["url"]) for h in brief["housekeeping"]]
        if brief["housekeeping_more"]:
            entries.append((f"...and {brief['housekeeping_more']} more repos", [], ""))
        sections.append(("Housekeeping", entries))
    return sections


def render(brief):
    since = (
        f"Changes since {brief['baseline_at'][:10]}."
        if brief.get("baseline_at")
        else "First run: there is no earlier snapshot to compare with. Run with --save-state to start tracking changes."
    )
    text = [_title(brief), _headline(brief), since]
    md = [f"# {_title(brief)}", "", f"**{_headline(brief)}**", "", since]
    page = [f"<h1>{html.escape(_title(brief))}</h1>", f"<p><strong>{html.escape(_headline(brief))}</strong></p>", f"<p>{html.escape(since)}</p>"]
    for warning in brief.get("warnings", []):
        text += ["", "Note: " + warning]
        md += ["", f"> Note: {warning}"]
        page.append(f"<p><em>Note: {html.escape(warning)}</em></p>")
    for heading, entries in _sections(brief):
        if heading:
            text += ["", heading.upper()]
            md += ["", f"## {heading}", ""]
            page.append(f"<h2>{html.escape(heading)}</h2>")
        numbered = bool(heading) and not heading.startswith("No longer")
        tag = "ol" if numbered else "ul"
        page.append(f"<{tag}>")
        for n, (title, details, url) in enumerate(entries, 1):
            link = _safe_url(url)
            text.append(f"{n}. {title}" if numbered else title)
            text += [f"   {line}" for line in details if line]
            if link:
                text.append(f"   {link}")
            md.append(f"{n}. **{title}**" if numbered else title)
            md += [f"   - {line}" for line in details if line]
            if link:
                md.append(f"   - {link}")
            shown = html.escape(title)
            shown = f'<a href="{html.escape(link, quote=True)}">{shown}</a>' if link else shown
            body = "".join(f"<br>{html.escape(line)}" for line in details if line)
            page.append(f"<li>{shown}{body}</li>")
        page.append(f"</{tag}>")
    document = (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>" + html.escape(_title(brief)) + "</title></head>"
        "<body style=\"font-family:sans-serif;max-width:640px;margin:2em auto;line-height:1.5\">" + "".join(page) + "</body></html>"
    )
    return {"title": _title(brief), "text": "\n".join(text), "markdown": "\n".join(md), "html": document}
