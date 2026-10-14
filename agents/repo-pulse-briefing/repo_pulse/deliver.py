"""Opt-in delivery of a rendered brief to a webhook.

Delivery never happens unless the caller asks for it AND a webhook is configured. Gmail is not
included on purpose: OAuth needs real credentials, so it could not be tested here.

Safety rules, each covered by a test:
  * https only. Plain http is accepted for loopback hosts, and only when explicitly allowed.
  * Redirects are not followed, so a webhook cannot bounce the request somewhere else.
  * Results never contain the URL path or query, or the token. Only the host is reported.
"""

import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlparse

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class DeliveryError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def default_post(url, headers, body, timeout=20):
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as exc:  # includes 3xx, because redirects are refused
        return exc.code
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DeliveryError(str(getattr(exc, "reason", exc))) from exc


def _result(status, detail, attempted=False, sent=False):
    return {"attempted": attempted, "sent": sent, "status": status, "detail": detail}


def deliver(rendered, env=None, post=default_post, allow_local=None):
    env = os.environ if env is None else env
    if allow_local is None:
        allow_local = env.get("REPO_PULSE_ALLOW_LOCAL_WEBHOOK") == "1"
    url = env.get("REPO_PULSE_WEBHOOK_URL", "")
    mode = (env.get("REPO_PULSE_DELIVERY") or ("webhook" if url else "")).lower()
    if mode != "webhook":
        return _result("not_configured", "Set REPO_PULSE_WEBHOOK_URL to deliver briefs. Nothing was sent.")
    if not url:
        return _result("misconfigured", "REPO_PULSE_DELIVERY=webhook needs REPO_PULSE_WEBHOOK_URL.")
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not (parsed.scheme == "https" or (parsed.scheme == "http" and host in LOCAL_HOSTS and allow_local)):
        return _result("rejected", "The webhook URL must use https. Nothing was sent.")
    headers = {"Content-Type": "application/json", "User-Agent": "repo-pulse-briefing"}
    token = env.get("REPO_PULSE_WEBHOOK_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps({key: rendered[key] for key in ("title", "text", "markdown", "html")}).encode("utf-8")
    try:
        status = post(url, headers, body)
    except DeliveryError as exc:
        return _result("error", f"Could not reach {host}: {exc}", attempted=True)
    if 200 <= status < 300:
        return _result("sent", f"{host} accepted the brief (HTTP {status}).", attempted=True, sent=True)
    return _result("error", f"{host} answered HTTP {status}.", attempted=True)
