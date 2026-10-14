"""Scheduler-facing HTTP hooks. Run with:  uvicorn repo_pulse.api:app --port 8000

Accounts come from the REPO_PULSE_ACCOUNTS environment variable, never from the request, so a caller
cannot make the server query arbitrary accounts. Anything that can send or save state is fail-closed:
it needs REPO_PULSE_TRIGGER_TOKEN to be set on the server and the same value in the X-Pulse-Token header.
"""

import hmac
import json
import os

from fastapi import FastAPI, HTTPException, Request

from .deliver import default_post
from .github import GitHubError, default_fetch
from .service import clamp_top_n, parse_accounts, run_pulse


def _as_bool(value, default):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes"}:
            return True
        if lowered in {"0", "false", "no"}:
            return False
    return default


def create_app(env=None, fetch=default_fetch, post=default_post):
    app = FastAPI(title="Repo Pulse scheduler API", description="Dry-run by default. Sending needs a trigger token.")

    def environment():
        return os.environ if env is None else env

    def run(payload, deliver_brief):
        e = environment()
        accounts = parse_accounts(e.get("REPO_PULSE_ACCOUNTS"))
        if not accounts:
            raise HTTPException(503, "REPO_PULSE_ACCOUNTS is not set on the server.")
        try:
            result = run_pulse(
                accounts,
                token=e.get("GITHUB_TOKEN"),
                state_path=e.get("REPO_PULSE_STATE"),
                top_n=clamp_top_n(payload.get("top_n")),
                deliver_brief=deliver_brief,
                save_state=deliver_brief and bool(e.get("REPO_PULSE_STATE")),
                fetch=fetch,
                post=post,
                env=e,
            )
        except GitHubError as exc:
            raise HTTPException(502, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"delivery": result["delivery"], "state_saved": result["state_saved"], "brief": result["rendered"]}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/pulse/dry-run")
    def dry_run(top_n: int = 5):
        return run({"top_n": top_n}, deliver_brief=False)

    @app.post("/pulse/trigger")
    async def trigger(request: Request):
        try:
            payload = json.loads((await request.body()) or b"{}")
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        send = _as_bool(payload.get("dry_run"), default=True) is False  # anything unclear stays a dry run
        if send:
            expected = environment().get("REPO_PULSE_TRIGGER_TOKEN")
            if not expected:
                raise HTTPException(403, "Sending is disabled: REPO_PULSE_TRIGGER_TOKEN is not set on the server.")
            provided = request.headers.get("x-pulse-token", "")
            if not hmac.compare_digest(provided.encode(), expected.encode()):
                raise HTTPException(401, "Missing or wrong X-Pulse-Token.")
        return run(payload, deliver_brief=send)

    return app


app = create_app()
