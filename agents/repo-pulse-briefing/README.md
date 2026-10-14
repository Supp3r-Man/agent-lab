# 📊 Repo Pulse Briefing

An always-on briefing agent for **your own GitHub accounts**. It reads your public repos, compares them with the last snapshot, and tells you what changed: new stars, forks, and open issues or pull requests, plus housekeeping nudges like missing topics or licenses.

This is an original agent. It borrows the *shape* of the Always-on Hacker News Briefing Agent in [awesome-llm-apps](https://github.com/Shubhamsaboo/awesome-llm-apps/tree/main/always_on_agents/always_on_hn_briefing_agent) (scout, rank, render, opt-in delivery, scheduler hook, thin ADK wrapper) but none of its code, and it makes some different safety choices.

## What it does

1. **Scout:** reads every repo of the accounts you list through the GitHub API. Forks and archived repos are skipped.
2. **Compare:** diffs against the snapshot saved on the last run.
3. **Rank:** scores each changed repo with plain arithmetic (see `repo_pulse/rank.py`) and keeps the reasons next to the score, so you can always see why something ranked where it did.
4. **Render:** produces text, Markdown and HTML.
5. **Deliver (opt-in):** posts to a webhook only when you ask it to.

No model is needed to produce the brief. The optional ADK wrapper only lets you ask for it in conversation.

## Run it

```bash
git clone https://github.com/Supp3r-Man/agent-lab.git
cd agent-lab/agents/repo-pulse-briefing
python -m repo_pulse --accounts your-account,your-other-account
```

That is a **dry run**: it reads GitHub, prints the brief, sends nothing and saves nothing. The core uses only the Python standard library (3.9 or newer; tested on 3.13 only).

```
Repo Pulse for your-account - 2026-10-14
43 repos | 0 stars | 0 forks | 10 open issues
First run: there is no earlier snapshot to compare with. Run with --save-state to start tracking changes.

HOUSEKEEPING
1. your-account/agent-lab: no topics
   Next: add topics so people can find it
```

To track changes, give it a state file and save a baseline. Later runs then report what changed since:

```bash
python -m repo_pulse --accounts you --state pulse-state.json --save-state    # first run: baseline
python -m repo_pulse --accounts you --state pulse-state.json                 # later: what changed (dry run)
```

Other options: `--format text|markdown|html|json`, `--top 1..10`. Set `GITHUB_TOKEN` for a higher rate limit. Unauthenticated GitHub allows 60 requests an hour, and each run needs about one request per account.

## Two rules that keep the changes honest

- **A dry run never moves the baseline.** Otherwise the next real run would show nothing.
- **If delivery fails, the baseline does not move.** Otherwise those changes would be lost.

Both are covered by tests.

## Deliver and schedule

Delivery is a webhook only: it POSTs JSON with `title`, `text`, `markdown` and `html` to any endpoint you choose. It has been tested against a local server, not against Slack or any other real service, so check that your endpoint accepts that payload:

```bash
export REPO_PULSE_WEBHOOK_URL=https://hooks.example.com/your-hook
export REPO_PULSE_WEBHOOK_TOKEN=optional-bearer-token
python -m repo_pulse --accounts you --state pulse-state.json --save-state --send
```

`--send` exits 1 if delivery fails, so a scheduler notices. Gmail is not included on purpose: OAuth needs real credentials, and it could not be tested here.

To run it on a schedule you have two options:

- **GitHub Actions:** `deploy/github-actions.yml` is a template (not active; copy it to `.github/workflows/`). It keeps the baseline in the Actions cache and writes the brief to the job summary. **It has not been run.** Try it in a test repository first.
- **HTTP hooks:** `uvicorn repo_pulse.api:app` serves `GET /pulse/dry-run` and `POST /pulse/trigger`. Set `REPO_PULSE_ACCOUNTS` on the server.

## Safety choices

| Choice | Why |
|---|---|
| Dry run is the default everywhere | Nothing is sent or saved by accident |
| Sending through the API needs `REPO_PULSE_TRIGGER_TOKEN` set on the server and the same value in an `X-Pulse-Token` header. If it is unset, sending is disabled | An unauthenticated endpoint that can send email or post to a webhook is an open relay. This fails closed |
| An unclear `dry_run` value (`"maybe"`, `7`, bad JSON) stays a dry run | Ambiguity should never cause a send |
| The API reads accounts from the server's environment, never the request | A caller cannot make the server query arbitrary accounts |
| Webhook URLs must be `https` (plain `http` only for loopback, and only with `REPO_PULSE_ALLOW_LOCAL_WEBHOOK=1`) | No cleartext tokens over the network |
| Redirects are not followed | A webhook cannot bounce the request somewhere else |
| Results never contain the webhook path, query or token, only the host | Secrets stay out of logs |
| HTML escapes everything and links only to `https://github.com/` | Repo names and descriptions come from GitHub and are untrusted |
| If any account fails to load, the whole run fails | A partial picture would report false "removed repo" changes |

## Ask for it in conversation (optional)

```bash
pip install google-adk
export GOOGLE_API_KEY=your-gemini-key REPO_PULSE_ACCOUNTS=you
```

`repo_pulse/agent.py` exposes `root_agent` with one tool, `preview_repo_pulse`. The model id defaults to `gemini-3-flash-preview` (copied from the upstream agent and not verified here); override it with `REPO_PULSE_MODEL`. **The tool and the agent object are tested. `adk web` and a live model call are not.**

## Configuration

| Variable | Used for |
|---|---|
| `REPO_PULSE_ACCOUNTS` | Accounts to watch, comma-separated (API and agent; the CLI can use `--accounts`) |
| `REPO_PULSE_STATE` | State file path |
| `GITHUB_TOKEN` | Optional, raises the GitHub rate limit |
| `REPO_PULSE_DELIVERY`, `REPO_PULSE_WEBHOOK_URL`, `REPO_PULSE_WEBHOOK_TOKEN` | Webhook delivery |
| `REPO_PULSE_ALLOW_LOCAL_WEBHOOK` | Set to `1` to allow `http://127.0.0.1` webhooks (for testing) |
| `REPO_PULSE_TRIGGER_TOKEN` | Enables sending through the API |
| `REPO_PULSE_MODEL` | Model id for the ADK wrapper |

## Limits, stated plainly

- **Changes are differences between snapshots, not events.** A star followed by an unstar between runs cancels out. A renamed repo shows as removed plus new.
- **It reads public data only.** Private repos are invisible to it, and so are traffic, clones and views.
- **The ranking is a heuristic.** The weights are in `rank.py`. They are reasonable defaults, not tuned on data.
- **Verified against real GitHub, read-only,** for two real accounts. **Delivery was verified only against a local test server,** never against Slack or any real service.
- **Not run:** the Actions template, `adk web`, and any live model call.

## Tests

```bash
python -m unittest discover -s tests
```

58 tests, about 15 seconds. The API and ADK tests skip if `fastapi` or `google-adk` are not installed. The tests include a real local HTTP server for delivery, and each safety rule above was checked by breaking it on purpose and confirming a test fails.
