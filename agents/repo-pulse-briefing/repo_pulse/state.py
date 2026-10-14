"""Remember the last snapshot so the next run can report what changed."""

import json
import os
import tempfile


def load(path):
    """Return (snapshot or None, warning or None). A missing file is normal; a corrupt one is reported."""
    if not path or not os.path.exists(path):
        return None, None
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict) or not isinstance(data.get("repos"), dict):
            raise ValueError("unexpected shape")
        return data, None
    except (OSError, ValueError) as exc:
        return None, f"Ignored unreadable state file {path} ({exc}); treating this as a first run."


def save(path, snapshot):
    """Write atomically, so a crash never leaves half a file that would be read as a first run."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".pulse-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def diff(previous, current):
    """Compare two snapshots. Repos are matched by full name, so a rename shows up as removed plus new."""
    prev, curr = previous["repos"], current["repos"]
    changes = {}
    for name, repo in curr.items():
        old = prev.get(name)
        if old is None:
            continue
        changes[name] = {
            "stars": repo["stars"] - old["stars"],
            "forks": repo["forks"] - old["forks"],
            "open_issues": repo["open_issues"] - old["open_issues"],
        }
    return {
        "new": sorted(set(curr) - set(prev)),
        "removed": sorted(set(prev) - set(curr)),
        "changes": changes,
    }
