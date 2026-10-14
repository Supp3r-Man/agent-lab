"""Turn a snapshot and its changes into a ranked, explainable list.

No model is involved. Every item carries the reasons behind its score, so a reader can see why
something ranked where it did, and the numbers below are the whole algorithm.
"""

from datetime import datetime, timezone

WEIGHTS = {"star": 3, "fork": 5, "issue": 6, "new_repo": 8, "active": 1}
CAPS = {"star": 30, "fork": 25, "issue": 30}
ACTIVE_DAYS = 7
STALE_DAYS = 180
MAX_HOUSEKEEPING = 10


def parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _score_repo(name, repo, delta, now):
    score, reasons, actions = 0, [], []
    change = (delta or {}).get("changes", {}).get(name)
    if delta and name in delta["new"]:
        score += WEIGHTS["new_repo"]
        reasons.append("new repository")
    if change:
        if change["stars"] > 0:
            score += min(change["stars"] * WEIGHTS["star"], CAPS["star"])
            reasons.append("+" + _plural(change["stars"], "star"))
        if change["forks"] > 0:
            score += min(change["forks"] * WEIGHTS["fork"], CAPS["fork"])
            reasons.append("+" + _plural(change["forks"], "fork"))
        if change["open_issues"] > 0:
            score += min(change["open_issues"] * WEIGHTS["issue"], CAPS["issue"])
            reasons.append(f"+{change['open_issues']} open issue(s) or pull request(s)")
            actions.append(f"Review the {change['open_issues']} new open issue(s) or pull request(s)")
    pushed = parse_time(repo["pushed_at"])
    if pushed and (now - pushed).days <= ACTIVE_DAYS and score > 0:
        score += WEIGHTS["active"]
        reasons.append("active this week")
    return score, reasons, actions


def _recency(repo):
    pushed = parse_time(repo["pushed_at"])
    return pushed.timestamp() if pushed else 0.0


def _housekeeping(snapshot, now):
    """One entry per repo, most recently active first, so the list starts with what people will see."""
    notes = []
    for name, repo in snapshot["repos"].items():
        if repo["fork"]:
            continue
        issues, actions = [], []
        if not repo["description"]:
            issues.append("no description")
            actions.append("add a one-line description")
        if not repo["topics"]:
            issues.append("no topics")
            actions.append("add topics so people can find it")
        if not repo["license"] or repo["license"] == "NOASSERTION":
            issues.append("no license")
            actions.append("add a license")
        pushed = parse_time(repo["pushed_at"])
        if pushed and repo["stars"] >= 1 and (now - pushed).days >= STALE_DAYS:
            issues.append(f"starred but untouched for {(now - pushed).days} days")
            actions.append("update it, or archive it")
        if issues:
            notes.append({"name": name, "url": repo["url"], "issues": issues, "actions": actions, "_recency": _recency(repo)})
    notes.sort(key=lambda n: (-n["_recency"], n["name"]))
    for note in notes:
        del note["_recency"]
    return notes[:MAX_HOUSEKEEPING], max(0, len(notes) - MAX_HOUSEKEEPING)


def rank(snapshot, delta, now=None, top_n=5):
    """delta is None on a first run, when there is nothing to compare with yet."""
    now = now or datetime.now(timezone.utc)
    repos = snapshot["repos"]
    items = []
    for name, repo in repos.items():
        score, reasons, actions = _score_repo(name, repo, delta, now)
        if score > 0:
            items.append({
                "name": name, "url": repo["url"], "score": score, "reasons": reasons,
                "next_action": actions[0] if actions else "",
                "delta": (delta or {}).get("changes", {}).get(name, {}),
            })
    items.sort(key=lambda item: (-item["score"], item["name"]))
    housekeeping, housekeeping_more = _housekeeping(snapshot, now)
    overview = sorted(repos.values(), key=lambda r: (-r["stars"], -_recency(r), r["name"]))[:top_n]
    return {
        "first_run": delta is None,
        "items": items[:top_n],
        "more": max(0, len(items) - top_n),
        "removed": list((delta or {}).get("removed", [])),
        "housekeeping": housekeeping,
        "housekeeping_more": housekeeping_more,
        "overview": [{"name": r["name"], "url": r["url"], "stars": r["stars"], "forks": r["forks"], "description": r["description"]} for r in overview],
        "totals": {
            "repos": len(repos),
            "stars": sum(r["stars"] for r in repos.values()),
            "forks": sum(r["forks"] for r in repos.values()),
            "open_issues": sum(r["open_issues"] for r in repos.values()),
        },
    }
