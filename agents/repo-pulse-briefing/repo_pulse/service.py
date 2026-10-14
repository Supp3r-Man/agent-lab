"""Run one briefing: read GitHub, compare with the last snapshot, rank, render, optionally deliver.

Defaults are safe. A run delivers nothing and writes no state unless the caller asks. Two rules keep
the deltas honest:
  * a dry run never advances the saved baseline, or the next real run would show no changes
  * if delivery was requested and failed, the baseline is not advanced, so those changes are not lost
"""

import os
from datetime import datetime, timezone

from . import state
from .deliver import default_post, deliver
from .github import GitHubClient, default_fetch, take_snapshot
from .rank import rank
from .render import render

MAX_ACCOUNTS = 10


def clamp_top_n(value, default=5):
    try:
        return max(1, min(int(value), 10))
    except (TypeError, ValueError):
        return default


def parse_accounts(value):
    seen, accounts = set(), []
    for part in (value or "").replace(";", ",").split(","):
        name = part.strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            accounts.append(name)
    return accounts


def run_pulse(
    accounts,
    *,
    token=None,
    state_path=None,
    top_n=5,
    deliver_brief=False,
    save_state=False,
    now=None,
    fetch=default_fetch,
    post=default_post,
    env=None,
):
    if isinstance(accounts, str):
        accounts = parse_accounts(accounts)
    if not accounts:
        raise ValueError("No GitHub accounts given. Pass --accounts or set REPO_PULSE_ACCOUNTS.")
    if len(accounts) > MAX_ACCOUNTS:
        raise ValueError(f"At most {MAX_ACCOUNTS} accounts per run.")
    if save_state and not state_path:
        raise ValueError("Saving state needs a state file path.")
    now = now or datetime.now(timezone.utc)
    top_n = clamp_top_n(top_n)

    snapshot = take_snapshot(accounts, GitHubClient(token, fetch), now)
    previous, warning = state.load(state_path)
    delta = state.diff(previous, snapshot) if previous else None
    brief = {
        **rank(snapshot, delta, now, top_n),
        "accounts": list(accounts),
        "generated_at": now.isoformat(),
        "baseline_at": previous["taken_at"] if previous else None,
        "warnings": [warning] if warning else [],
    }
    rendered = render(brief)

    delivery = {"attempted": False, "sent": False, "status": "dry_run", "detail": "Nothing was sent."}
    if deliver_brief:
        delivery = deliver(rendered, os.environ if env is None else env, post)

    saved = False
    if save_state and (not deliver_brief or delivery["sent"]):
        state.save(state_path, snapshot)
        saved = True
    return {"brief": brief, "rendered": rendered, "delivery": delivery, "state_saved": saved}
