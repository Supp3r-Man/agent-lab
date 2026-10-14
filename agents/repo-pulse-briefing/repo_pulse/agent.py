"""Optional Google ADK wrapper, so the brief can be requested in conversation (for example with ADK Web).

The brief itself never needs a model. The model here only decides when to call the tool and relays
its text. If google-adk is not installed, root_agent is None and the rest of the package still works.
"""

import os

from .github import GitHubError
from .service import parse_accounts, run_pulse


def preview_repo_pulse(top_n: int = 5) -> dict:
    """Preview the GitHub repo pulse brief for the configured accounts.

    Args:
        top_n: How many changed repos to include, from 1 to 10.

    Returns:
        The brief as text, Markdown and HTML, or an error message. Nothing is sent or saved.
    """
    accounts = parse_accounts(os.environ.get("REPO_PULSE_ACCOUNTS"))
    if not accounts:
        return {"error": "REPO_PULSE_ACCOUNTS is not set. Set it to a comma-separated list of GitHub accounts."}
    try:
        result = run_pulse(accounts, token=os.environ.get("GITHUB_TOKEN"), state_path=os.environ.get("REPO_PULSE_STATE"), top_n=top_n)
    except (GitHubError, ValueError) as exc:
        return {"error": str(exc)}
    return result["rendered"]


INSTRUCTION = """
You are Repo Pulse, a briefing assistant for the owner of some GitHub accounts.

- When asked for the brief, a digest, what changed, or the state of the repos, call preview_repo_pulse
  and relay its text. Do not invent numbers, repos or changes that the tool did not return.
- If the tool returns an error, say what it says, plainly.
- You can only read and summarize. Never claim to have sent a message, saved a baseline or scheduled anything.
- Keep answers short: the ranked changes first, then housekeeping.
"""

try:
    from google.adk.agents import LlmAgent

    root_agent = LlmAgent(
        name="repo_pulse",
        model=os.environ.get("REPO_PULSE_MODEL", "gemini-3-flash-preview"),
        description="Briefs the owner on new stars, forks and issues across their GitHub accounts, and on housekeeping.",
        instruction=INSTRUCTION,
        tools=[preview_repo_pulse],
    )
except ImportError:  # google-adk is optional
    root_agent = None
