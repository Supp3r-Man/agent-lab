"""Read public repository data from the GitHub API. Standard library only.

The HTTP call is a plain function so tests can replace it: fetch(url, headers) -> (status, headers, body).
"""

import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone

API = "https://api.github.com"
ACCOUNT_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
PAGE_SIZE = 100


class GitHubError(RuntimeError):
    """A failure with a message that is safe to show to the user."""


def default_fetch(url, headers, timeout=15):
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GitHubError(f"Could not reach GitHub: {exc}") from exc


def _next_link(headers):
    for key, value in headers.items():
        if key.lower() == "link":
            match = re.search(r'<([^>]+)>;\s*rel="next"', value)
            if match:
                return match.group(1)
    return None


def _header(headers, name):
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return None


class GitHubClient:
    def __init__(self, token=None, fetch=default_fetch, max_pages=3):
        self.fetch = fetch
        self.max_pages = max_pages
        self.headers = {"Accept": "application/vnd.github+json", "User-Agent": "repo-pulse-briefing"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def list_repos(self, account):
        if not ACCOUNT_RE.match(account or ""):
            raise GitHubError(f"'{account}' is not a valid GitHub account name.")
        url = f"{API}/users/{account}/repos?per_page={PAGE_SIZE}&type=owner&sort=pushed"
        repos = []
        for _ in range(self.max_pages):
            status, headers, body = self.fetch(url, self.headers)
            if status == 404:
                raise GitHubError(f"No GitHub account named '{account}'.")
            if status in (403, 429) and _header(headers, "x-ratelimit-remaining") == "0":
                reset = _header(headers, "x-ratelimit-reset")
                when = ""
                if reset and reset.isdigit():
                    when = " Resets at " + datetime.fromtimestamp(int(reset), timezone.utc).strftime("%H:%M UTC") + "."
                raise GitHubError("GitHub rate limit reached. Set GITHUB_TOKEN for a higher limit." + when)
            if status != 200:
                raise GitHubError(f"GitHub returned HTTP {status} for '{account}'.")
            try:
                page = json.loads(body)
            except ValueError as exc:
                raise GitHubError("GitHub returned something that is not JSON.") from exc
            if not isinstance(page, list):
                raise GitHubError("GitHub returned an unexpected response shape.")
            repos.extend(page)
            url = _next_link(headers)
            if not url or len(page) < PAGE_SIZE:
                break
        return repos


def _repo_entry(raw):
    license_info = raw.get("license") or {}
    return {
        "name": raw["full_name"],
        "url": raw.get("html_url") or f"https://github.com/{raw['full_name']}",
        "description": raw.get("description") or "",
        "stars": int(raw.get("stargazers_count", 0)),
        "forks": int(raw.get("forks_count", 0)),
        "open_issues": int(raw.get("open_issues_count", 0)),
        "pushed_at": raw.get("pushed_at") or "",
        "license": license_info.get("spdx_id") or "",
        "topics": list(raw.get("topics") or []),
        "fork": bool(raw.get("fork")),
        "archived": bool(raw.get("archived")),
    }


def take_snapshot(accounts, client, now=None, include_forks=False, include_archived=False):
    """Read every account. If any account fails the whole run fails, so a brief never reports a partial picture."""
    now = now or datetime.now(timezone.utc)
    repos = {}
    for account in accounts:
        for raw in client.list_repos(account):
            entry = _repo_entry(raw)
            if (entry["fork"] and not include_forks) or (entry["archived"] and not include_archived):
                continue
            repos[entry["name"]] = entry
    return {"taken_at": now.isoformat(), "accounts": list(accounts), "repos": repos}
