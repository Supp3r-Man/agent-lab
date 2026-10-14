"""Tests for repo_pulse. Standard library only for the core; the API and ADK tests skip if those packages are missing.

Run from the repo_pulse folder:  python -m unittest discover -s tests -v
"""

import contextlib
import io
import json
import os
import re
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from repo_pulse import __main__ as cli  # noqa: E402
from repo_pulse import deliver, rank, render, service, state  # noqa: E402
from repo_pulse.github import GitHubClient, GitHubError, take_snapshot  # noqa: E402

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


def raw(name, stars=0, forks=0, issues=0, days_ago=30, description="A repo", topics=("topic",), license="MIT", fork=False, archived=False):
    pushed = (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")
    return {
        "full_name": name, "html_url": f"https://github.com/{name}", "description": description,
        "stargazers_count": stars, "forks_count": forks, "open_issues_count": issues, "pushed_at": pushed,
        "license": {"spdx_id": license} if license else None, "topics": list(topics), "fork": fork, "archived": archived,
    }


def fake_fetch(by_account, calls=None):
    """by_account maps an account to a list of raw repos (200), an int status, or a (status, headers, body) tuple."""
    def fetch(url, headers):
        if calls is not None:
            calls.append((url, headers))
        account = re.search(r"/users/([^/]+)/repos", url).group(1)
        reply = by_account[account]
        if isinstance(reply, int):
            return reply, {}, "{}"
        if isinstance(reply, tuple):
            return reply
        return 200, {}, json.dumps(reply)
    return fetch


def snapshot_of(*repos, taken="2026-10-07T12:00:00+00:00"):
    client = GitHubClient(fetch=fake_fetch({"me": list(repos)}))
    snap = take_snapshot(["me"], client, now=NOW)
    snap["taken_at"] = taken
    return snap


class GitHubTests(unittest.TestCase):
    def test_maps_fields(self):
        snap = take_snapshot(["me"], GitHubClient(fetch=fake_fetch({"me": [raw("me/a", stars=3, forks=1, issues=2, license=None, topics=())]})), now=NOW)
        repo = snap["repos"]["me/a"]
        self.assertEqual((repo["stars"], repo["forks"], repo["open_issues"], repo["license"], repo["topics"]), (3, 1, 2, "", []))

    def test_follows_pagination(self):
        page1 = [raw(f"me/r{i}") for i in range(100)]
        page2 = [raw("me/last")]
        calls = []

        def fetch(url, headers):
            calls.append(url)
            if "page=2" in url:
                return 200, {}, json.dumps(page2)
            return 200, {"Link": '<https://api.github.com/users/me/repos?page=2>; rel="next"'}, json.dumps(page1)

        repos = GitHubClient(fetch=fetch).list_repos("me")
        self.assertEqual((len(repos), len(calls)), (101, 2))

    def test_stops_at_max_pages(self):
        page = [raw(f"me/r{i}") for i in range(100)]
        calls = []

        def fetch(url, headers):
            calls.append(url)
            return 200, {"Link": '<https://api.github.com/users/me/repos?page=9>; rel="next"'}, json.dumps(page)

        GitHubClient(fetch=fetch, max_pages=2).list_repos("me")
        self.assertEqual(len(calls), 2)

    def test_forks_and_archived_are_skipped_unless_asked(self):
        data = [raw("me/keep"), raw("me/forked", fork=True), raw("me/old", archived=True)]
        client = GitHubClient(fetch=fake_fetch({"me": data}))
        self.assertEqual(list(take_snapshot(["me"], client, now=NOW)["repos"]), ["me/keep"])
        self.assertEqual(len(take_snapshot(["me"], client, now=NOW, include_forks=True, include_archived=True)["repos"]), 3)

    def test_unknown_account_and_rate_limit_messages(self):
        with self.assertRaisesRegex(GitHubError, "No GitHub account named 'ghost'"):
            GitHubClient(fetch=fake_fetch({"ghost": 404})).list_repos("ghost")
        reset = str(int(NOW.timestamp()))
        limited = (403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": reset}, "{}")
        with self.assertRaisesRegex(GitHubError, "rate limit.*GITHUB_TOKEN.*12:00 UTC"):
            GitHubClient(fetch=fake_fetch({"me": limited})).list_repos("me")
        with self.assertRaisesRegex(GitHubError, "HTTP 403"):
            GitHubClient(fetch=fake_fetch({"me": 403})).list_repos("me")

    def test_bad_account_names_never_reach_the_network(self):
        calls = []
        client = GitHubClient(fetch=fake_fetch({}, calls))
        for bad in ["", "a b", "../etc", "x" * 40, "-lead", "a/b", "a?b=1"]:
            with self.assertRaises(GitHubError, msg=bad):
                client.list_repos(bad)
        self.assertEqual(calls, [])

    def test_bad_bodies_are_reported(self):
        with self.assertRaisesRegex(GitHubError, "not JSON"):
            GitHubClient(fetch=fake_fetch({"me": (200, {}, "<html>")})).list_repos("me")
        with self.assertRaisesRegex(GitHubError, "unexpected response"):
            GitHubClient(fetch=fake_fetch({"me": (200, {}, '{"message": "x"}')})).list_repos("me")

    def test_token_is_sent_as_bearer_and_never_leaks_into_errors(self):
        calls = []
        client = GitHubClient(token="ghp_SECRET", fetch=fake_fetch({"me": 500}, calls))
        with self.assertRaises(GitHubError) as err:
            client.list_repos("me")
        self.assertEqual(calls[0][1]["Authorization"], "Bearer ghp_SECRET")
        self.assertNotIn("ghp_SECRET", str(err.exception))
        self.assertNotIn("Authorization", GitHubClient(fetch=fake_fetch({})).headers)

    def test_one_failing_account_fails_the_whole_run(self):
        client = GitHubClient(fetch=fake_fetch({"a": [raw("a/x")], "b": 404}))
        with self.assertRaises(GitHubError):
            take_snapshot(["a", "b"], client, now=NOW)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pulse_state_")
        self.path = os.path.join(self.dir, "sub", "state.json")

    def test_missing_file_is_a_normal_first_run(self):
        self.assertEqual(state.load(self.path), (None, None))
        self.assertEqual(state.load(None), (None, None))

    def test_roundtrip_creates_folders_and_leaves_no_temp_files(self):
        snap = snapshot_of(raw("me/a", stars=2))
        state.save(self.path, snap)
        state.save(self.path, snap)
        loaded, warning = state.load(self.path)
        self.assertEqual((loaded["repos"]["me/a"]["stars"], warning), (2, None))
        self.assertEqual([f for f in os.listdir(os.path.dirname(self.path)) if f.endswith(".tmp")], [])

    def test_a_crash_while_saving_keeps_the_previous_baseline_intact(self):
        state.save(self.path, snapshot_of(raw("me/a", stars=2)))
        before = open(self.path, encoding="utf-8").read()
        with mock.patch.object(state.json, "dump", side_effect=RuntimeError("disk full")):
            with self.assertRaises(RuntimeError):
                state.save(self.path, snapshot_of(raw("me/a", stars=99)))
        self.assertEqual(open(self.path, encoding="utf-8").read(), before)
        self.assertEqual([f for f in os.listdir(os.path.dirname(self.path)) if f.endswith(".tmp")], [])

    def test_corrupt_or_wrong_shape_is_reported_not_fatal(self):
        os.makedirs(os.path.dirname(self.path))
        for content in ("{not json", '{"repos": []}', "[]"):
            with open(self.path, "w", encoding="utf-8") as handle:
                handle.write(content)
            loaded, warning = state.load(self.path)
            self.assertIsNone(loaded)
            self.assertIn("first run", warning)

    def test_diff(self):
        old = snapshot_of(raw("me/a", stars=1, issues=1), raw("me/gone"), raw("me/same", stars=5))
        new = snapshot_of(raw("me/a", stars=4, forks=2, issues=0), raw("me/new"), raw("me/same", stars=5))
        d = state.diff(old, new)
        self.assertEqual((d["new"], d["removed"]), (["me/new"], ["me/gone"]))
        self.assertEqual(d["changes"]["me/a"], {"stars": 3, "forks": 2, "open_issues": -1})
        self.assertEqual(d["changes"]["me/same"], {"stars": 0, "forks": 0, "open_issues": 0})


class RankTests(unittest.TestCase):
    def ranked(self, old, new, top_n=5):
        return rank.rank(new, state.diff(old, new), NOW, top_n)

    def test_scores_are_the_documented_arithmetic(self):
        old = snapshot_of(raw("me/a", days_ago=2), raw("me/quiet"))
        new = snapshot_of(raw("me/a", stars=2, forks=1, issues=1, days_ago=2), raw("me/quiet"))
        items = self.ranked(old, new)["items"]
        self.assertEqual(len(items), 1)
        item = items[0]
        # 2 stars*3 + 1 fork*5 + 1 issue*6 + 1 for activity this week
        self.assertEqual(item["score"], 6 + 5 + 6 + 1)
        self.assertEqual(item["reasons"], ["+2 stars", "+1 fork", "+1 open issue(s) or pull request(s)", "active this week"])
        self.assertIn("Review the 1 new open issue", item["next_action"])

    def test_caps_new_repos_and_ordering(self):
        old = snapshot_of(raw("me/b"), raw("me/c"))
        new = snapshot_of(raw("me/b", stars=20, days_ago=90), raw("me/c", stars=1, days_ago=90), raw("me/d", days_ago=90))
        items = self.ranked(old, new)["items"]
        self.assertEqual([(i["name"], i["score"]) for i in items], [("me/b", 30), ("me/d", 8), ("me/c", 3)])  # star score capped at 30

    def test_losses_and_unchanged_repos_are_not_scored(self):
        old = snapshot_of(raw("me/a", stars=5, issues=3))
        new = snapshot_of(raw("me/a", stars=2, issues=1))
        self.assertEqual(self.ranked(old, new)["items"], [])

    def test_top_n_and_more_count(self):
        old = snapshot_of(*[raw(f"me/r{i}") for i in range(4)])
        new = snapshot_of(*[raw(f"me/r{i}", stars=i + 1, days_ago=90) for i in range(4)])
        result = self.ranked(old, new, top_n=2)
        self.assertEqual((len(result["items"]), result["more"]), (2, 2))
        self.assertEqual(result["items"][0]["name"], "me/r3")

    def test_first_run_has_no_items_but_an_overview(self):
        snap = snapshot_of(raw("me/old", stars=1, days_ago=100), raw("me/popular", stars=9), raw("me/fresh", stars=1, days_ago=1))
        result = rank.rank(snap, None, NOW, top_n=2)
        self.assertEqual((result["first_run"], result["items"]), (True, []))
        self.assertEqual([r["name"] for r in result["overview"]], ["me/popular", "me/fresh"])  # stars, then recency
        self.assertEqual(result["totals"], {"repos": 3, "stars": 11, "forks": 0, "open_issues": 0})

    def test_housekeeping_is_one_entry_per_repo_and_most_recent_first(self):
        snap = snapshot_of(
            raw("me/bare", description="", topics=(), license=None, days_ago=2),
            raw("me/nolicense", license="NOASSERTION", days_ago=5),
            raw("me/stale", stars=2, days_ago=400),
            raw("me/fine"),
            raw("me/forked", description="", fork=True),
        )
        notes = rank.rank(snap, None, NOW)["housekeeping"]
        self.assertEqual([n["name"] for n in notes], ["me/bare", "me/nolicense", "me/stale"])
        self.assertEqual(notes[0]["issues"], ["no description", "no topics", "no license"])
        self.assertIn("untouched for 400 days", notes[2]["issues"][0])

    def test_housekeeping_is_capped_with_a_remainder_count(self):
        snap = snapshot_of(*[raw(f"me/r{i}", topics=()) for i in range(14)])
        result = rank.rank(snap, None, NOW)
        self.assertEqual((len(result["housekeeping"]), result["housekeeping_more"]), (10, 4))


def brief_for(old, new, **extra):
    delta = state.diff(old, new) if old else None
    return {**rank.rank(new, delta, NOW, 5), "accounts": ["me"], "generated_at": NOW.isoformat(),
            "baseline_at": old["taken_at"] if old else None, "warnings": [], **extra}


class RenderTests(unittest.TestCase):
    def test_hostile_github_text_is_escaped_and_unsafe_links_are_dropped(self):
        evil = raw("me/<script>alert(1)</script>", stars=0, description='<img src=x onerror="alert(2)">')
        old = snapshot_of(evil)
        new = snapshot_of(raw("me/<script>alert(1)</script>", stars=3, description='<img src=x onerror="alert(2)">'))
        new["repos"]["me/<script>alert(1)</script>"]["url"] = "javascript:alert(3)"
        out = render.render(brief_for(old, new))
        self.assertNotIn("<script>", out["html"])
        self.assertNotIn("<img", out["html"])
        self.assertNotIn("javascript:", out["html"])
        self.assertIn("&lt;script&gt;", out["html"])

    def test_only_github_links_are_linked(self):
        old = snapshot_of(raw("me/a"))
        new = snapshot_of(raw("me/a", stars=1))
        out = render.render(brief_for(old, new))
        self.assertIn('<a href="https://github.com/me/a">', out["html"])
        new["repos"]["me/a"]["url"] = "https://evil.example/me/a"
        self.assertNotIn("evil.example", render.render(brief_for(old, new))["html"])

    def test_text_and_markdown_content(self):
        old = snapshot_of(raw("me/a", issues=0))
        new = snapshot_of(raw("me/a", stars=2, issues=1))
        out = render.render(brief_for(old, new))
        self.assertIn("Repo Pulse for me - 2026-10-14", out["text"])
        self.assertIn("NEEDS ATTENTION", out["text"])
        self.assertIn("Changes since 2026-10-07.", out["text"])
        self.assertIn("## Needs attention", out["markdown"])
        self.assertTrue(out["text"].isascii())

    def test_quiet_week_removed_repos_and_warnings(self):
        old = snapshot_of(raw("me/a"), raw("me/gone"))
        new = snapshot_of(raw("me/a"))
        out = render.render(brief_for(old, new, warnings=["Ignored unreadable state file"]))
        self.assertIn("NOTHING CHANGED", out["text"])
        self.assertIn("NO LONGER VISIBLE", out["text"])
        self.assertIn("me/gone", out["text"])
        self.assertIn("Note: Ignored unreadable state file", out["text"])

    def test_first_run_never_claims_a_baseline_was_saved(self):
        out = render.render(brief_for(None, snapshot_of(raw("me/a"))))
        self.assertNotIn("saved", out["text"].lower().replace("--save-state", ""))
        self.assertIn("--save-state", out["text"])


class _Receiver(BaseHTTPRequestHandler):
    hits = []
    mode = "ok"

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        type(self).hits.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": json.loads(body)})
        if type(self).mode == "redirect":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/elsewhere")
            self.end_headers()
        elif type(self).mode == "fail":
            self.send_response(500)
            self.end_headers()
        else:
            self.send_response(204)
            self.end_headers()

    def log_message(self, *args):
        pass


class DeliverTests(unittest.TestCase):
    RENDERED = {"title": "T", "text": "x", "markdown": "m", "html": "<p>h</p>"}

    def test_nothing_is_sent_unless_configured(self):
        result = deliver.deliver(self.RENDERED, env={})
        self.assertEqual((result["status"], result["attempted"], result["sent"]), ("not_configured", False, False))
        self.assertEqual(deliver.deliver(self.RENDERED, env={"REPO_PULSE_DELIVERY": "webhook"})["status"], "misconfigured")

    def test_https_webhook_gets_json_and_bearer_token(self):
        seen = {}

        def post(url, headers, body):
            seen.update(url=url, headers=headers, body=json.loads(body))
            return 200

        env = {"REPO_PULSE_WEBHOOK_URL": "https://hooks.example.com/secret/path?key=abc", "REPO_PULSE_WEBHOOK_TOKEN": "tok123"}
        result = deliver.deliver(self.RENDERED, env=env, post=post)
        self.assertTrue(result["sent"])
        self.assertEqual(seen["headers"]["Authorization"], "Bearer tok123")
        self.assertEqual(sorted(seen["body"]), ["html", "markdown", "text", "title"])
        shown = json.dumps(result)
        for secret in ("tok123", "secret", "key=abc"):
            self.assertNotIn(secret, shown)
        self.assertIn("hooks.example.com", shown)

    def test_plain_http_is_refused_except_for_allowed_loopback(self):
        def never(*args):
            raise AssertionError("must not post")

        for url, allow in [("http://example.com/x", True), ("http://example.com/x", False), ("http://127.0.0.1:9/x", False), ("ftp://x/y", True)]:
            result = deliver.deliver(self.RENDERED, env={"REPO_PULSE_WEBHOOK_URL": url}, post=never, allow_local=allow)
            self.assertEqual((result["status"], result["attempted"]), ("rejected", False), url)

    def serve(self, mode):
        _Receiver.hits, _Receiver.mode = [], mode
        server = HTTPServer(("127.0.0.1", 0), _Receiver)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_port}/hook"

    def test_real_loopback_delivery(self):
        url = self.serve("ok")
        result = deliver.deliver(self.RENDERED, env={"REPO_PULSE_WEBHOOK_URL": url, "REPO_PULSE_WEBHOOK_TOKEN": "t"}, allow_local=True)
        self.assertTrue(result["sent"])
        self.assertEqual((len(_Receiver.hits), _Receiver.hits[0]["auth"], _Receiver.hits[0]["body"]["title"]), (1, "Bearer t", "T"))

    def test_redirects_are_not_followed(self):
        url = self.serve("redirect")
        result = deliver.deliver(self.RENDERED, env={"REPO_PULSE_WEBHOOK_URL": url}, allow_local=True)
        self.assertEqual((result["sent"], result["status"]), (False, "error"))
        self.assertIn("302", result["detail"])
        self.assertEqual(len(_Receiver.hits), 1)  # the redirect target was never contacted

    def test_server_errors_and_unreachable_hosts_are_reported(self):
        url = self.serve("fail")
        self.assertIn("500", deliver.deliver(self.RENDERED, env={"REPO_PULSE_WEBHOOK_URL": url}, allow_local=True)["detail"])
        dead = deliver.deliver(self.RENDERED, env={"REPO_PULSE_WEBHOOK_URL": "http://127.0.0.1:1/x"}, allow_local=True)
        self.assertEqual((dead["status"], dead["attempted"], dead["sent"]), ("error", True, False))


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.state = os.path.join(tempfile.mkdtemp(prefix="pulse_svc_"), "state.json")

    def run_pulse(self, repos, **kwargs):
        kwargs.setdefault("now", NOW)
        return service.run_pulse(["me"], fetch=fake_fetch({"me": repos}), state_path=self.state, **kwargs)

    def test_a_dry_run_sends_nothing_and_saves_nothing(self):
        result = self.run_pulse([raw("me/a")])
        self.assertEqual((result["delivery"]["status"], result["state_saved"]), ("dry_run", False))
        self.assertFalse(os.path.exists(self.state))

    def test_dry_runs_do_not_hide_changes_from_the_next_real_run(self):
        self.run_pulse([raw("me/a")], save_state=True)
        self.run_pulse([raw("me/a", stars=5)])  # a dry run in between
        real = self.run_pulse([raw("me/a", stars=5)])
        self.assertEqual(real["brief"]["items"][0]["reasons"][0], "+5 stars")

    def test_second_run_reports_changes_since_the_saved_baseline(self):
        first = self.run_pulse([raw("me/a")], save_state=True)
        self.assertEqual((first["brief"]["first_run"], first["state_saved"]), (True, True))
        second = self.run_pulse([raw("me/a", stars=2), raw("me/new")])
        brief = second["brief"]
        self.assertEqual([i["name"] for i in brief["items"]], ["me/new", "me/a"])
        self.assertEqual(brief["baseline_at"], NOW.isoformat())

    def test_baseline_advances_only_after_delivery_succeeds(self):
        env = {"REPO_PULSE_WEBHOOK_URL": "https://hooks.example.com/x"}
        self.run_pulse([raw("me/a")], save_state=True)
        before = open(self.state, encoding="utf-8").read()
        failed = self.run_pulse([raw("me/a", stars=9)], deliver_brief=True, save_state=True, env=env, post=lambda *a: 500)
        self.assertEqual((failed["delivery"]["sent"], failed["state_saved"]), (False, False))
        unconfigured = self.run_pulse([raw("me/a", stars=9)], deliver_brief=True, save_state=True, env={})
        self.assertEqual((unconfigured["delivery"]["status"], unconfigured["state_saved"]), ("not_configured", False))
        self.assertEqual(open(self.state, encoding="utf-8").read(), before)
        sent = self.run_pulse([raw("me/a", stars=9)], deliver_brief=True, save_state=True, env=env, post=lambda *a: 200)
        self.assertEqual((sent["delivery"]["sent"], sent["state_saved"]), (True, True))

    def test_argument_validation(self):
        with self.assertRaises(ValueError):
            service.run_pulse([], fetch=fake_fetch({}))
        with self.assertRaises(ValueError):
            service.run_pulse(["me"], fetch=fake_fetch({"me": []}), save_state=True)
        with self.assertRaisesRegex(ValueError, "At most"):
            service.run_pulse([f"a{i}" for i in range(11)], fetch=fake_fetch({}))

    def test_helpers(self):
        self.assertEqual(service.parse_accounts(" a, B ;a,,c "), ["a", "B", "c"])
        self.assertEqual([service.clamp_top_n(v) for v in (0, 99, "7", "x", None)], [1, 10, 7, 5, 5])

    def test_a_failing_account_leaves_state_untouched(self):
        self.run_pulse([raw("me/a")], save_state=True)
        before = open(self.state, encoding="utf-8").read()
        with self.assertRaises(GitHubError):
            service.run_pulse(["me", "ghost"], fetch=fake_fetch({"me": [], "ghost": 404}), state_path=self.state, save_state=True, now=NOW)
        self.assertEqual(open(self.state, encoding="utf-8").read(), before)

    def test_corrupt_state_becomes_a_first_run_with_a_warning(self):
        with open(self.state, "w", encoding="utf-8") as handle:
            handle.write("{broken")
        result = self.run_pulse([raw("me/a")])
        self.assertTrue(result["brief"]["first_run"])
        self.assertIn("Ignored unreadable state file", result["rendered"]["text"])


class CliTests(unittest.TestCase):
    def run_cli(self, argv, repos=None, env=None):
        repos = [raw("me/a", stars=1)] if repos is None else repos
        patched = lambda *a, **k: service.run_pulse(*a, fetch=fake_fetch({"me": repos}), now=NOW, **k)  # noqa: E731
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(cli, "run_pulse", patched), mock.patch.dict(os.environ, env or {}, clear=True):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_no_accounts_is_a_usage_error(self):
        code, _, err = self.run_cli([])
        self.assertEqual(code, 2)
        self.assertIn("no accounts", err)

    def test_default_is_a_dry_run_that_prints_the_brief(self):
        code, out, _ = self.run_cli(["--accounts", "me"])
        self.assertEqual(code, 0)
        self.assertIn("Repo Pulse for me", out)

    def test_formats(self):
        _, out, _ = self.run_cli(["--accounts", "me", "--format", "json"])
        data = json.loads(out)
        self.assertEqual((data["delivery"]["status"], data["state_saved"]), ("dry_run", False))
        _, html_out, _ = self.run_cli(["--accounts", "me", "--format", "html"])
        self.assertTrue(html_out.startswith("<!doctype html>"))

    def test_accounts_can_come_from_the_environment(self):
        code, out, _ = self.run_cli([], env={"REPO_PULSE_ACCOUNTS": "me"})
        self.assertEqual(code, 0)
        self.assertIn("Repo Pulse for me", out)

    def test_send_without_a_webhook_fails_loudly_and_saves_nothing(self):
        path = os.path.join(tempfile.mkdtemp(), "s.json")
        code, _, err = self.run_cli(["--accounts", "me", "--send", "--save-state", "--state", path])
        self.assertEqual(code, 1)
        self.assertIn("not_configured", err)
        self.assertFalse(os.path.exists(path))

    def test_save_state_alone_writes_the_baseline(self):
        path = os.path.join(tempfile.mkdtemp(), "s.json")
        code, _, _ = self.run_cli(["--accounts", "me", "--save-state", "--state", path])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(path))

    def test_save_state_without_a_path_is_a_usage_error(self):
        code, _, err = self.run_cli(["--accounts", "me", "--save-state"])
        self.assertEqual(code, 2)
        self.assertIn("state file", err)

    def test_github_errors_exit_1(self):
        def boom(*a, **k):
            raise GitHubError("No GitHub account named 'me'.")

        err = io.StringIO()
        with mock.patch.object(cli, "run_pulse", boom), contextlib.redirect_stderr(err), mock.patch.dict(os.environ, {}, clear=True):
            code = cli.main(["--accounts", "me"])
        self.assertEqual(code, 1)
        self.assertIn("No GitHub account", err.getvalue())


try:
    from fastapi.testclient import TestClient

    from repo_pulse.api import create_app
except ImportError:  # the API is optional
    TestClient = None


@unittest.skipIf(TestClient is None, "fastapi not installed")
class ApiTests(unittest.TestCase):
    def client(self, env=None, repos=None, accounts=None, post=lambda *a: 204, calls=None):
        env = {"REPO_PULSE_ACCOUNTS": "me", **(env or {})}
        by_account = {a: (repos if repos is not None else [raw("me/a", stars=1)]) for a in (accounts or ["me"])}
        return TestClient(create_app(env=env, fetch=fake_fetch(by_account, calls), post=post))

    def test_health_and_dry_run(self):
        c = self.client()
        self.assertEqual(c.get("/health").json(), {"status": "ok"})
        body = c.get("/pulse/dry-run").json()
        self.assertEqual(body["delivery"]["status"], "dry_run")
        self.assertIn("Repo Pulse for me", body["brief"]["text"])

    def test_missing_accounts_config_is_a_503(self):
        c = TestClient(create_app(env={}, fetch=fake_fetch({})))
        self.assertEqual(c.get("/pulse/dry-run").status_code, 503)

    def test_trigger_defaults_to_a_dry_run_without_credentials(self):
        c = self.client()
        for kwargs in ({}, {"content": b"not json"}, {"json": {"dry_run": "maybe"}}, {"json": {"dry_run": 7}}, {"json": [1, 2]}):
            reply = c.post("/pulse/trigger", **kwargs)
            self.assertEqual((reply.status_code, reply.json()["delivery"]["status"]), (200, "dry_run"), kwargs)

    def test_sending_is_fail_closed(self):
        # No token configured on the server: sending is disabled even for a caller who sends a header.
        c = self.client()
        reply = c.post("/pulse/trigger", json={"dry_run": False}, headers={"X-Pulse-Token": "anything"})
        self.assertEqual(reply.status_code, 403)
        # Token configured: missing or wrong header is rejected.
        c = self.client(env={"REPO_PULSE_TRIGGER_TOKEN": "s3cret", "REPO_PULSE_WEBHOOK_URL": "https://hooks.example.com/x"})
        self.assertEqual(c.post("/pulse/trigger", json={"dry_run": False}).status_code, 401)
        self.assertEqual(c.post("/pulse/trigger", json={"dry_run": False}, headers={"X-Pulse-Token": "wrong"}).status_code, 401)
        self.assertEqual(c.post("/pulse/trigger", json={"dry_run": "false"}).status_code, 401)  # the string form counts too

    def test_authorised_send_delivers_and_saves_state(self):
        path = os.path.join(tempfile.mkdtemp(), "state.json")
        env = {"REPO_PULSE_TRIGGER_TOKEN": "s3cret", "REPO_PULSE_WEBHOOK_URL": "https://hooks.example.com/x", "REPO_PULSE_STATE": path}
        reply = self.client(env=env).post("/pulse/trigger", json={"dry_run": False}, headers={"X-Pulse-Token": "s3cret"})
        body = reply.json()
        self.assertEqual((reply.status_code, body["delivery"]["sent"], body["state_saved"]), (200, True, True))
        self.assertTrue(os.path.exists(path))

    def test_accounts_come_only_from_the_server_environment(self):
        calls = []
        c = self.client(calls=calls)
        c.post("/pulse/trigger", json={"accounts": ["someone-else"], "dry_run": True})
        self.assertTrue(calls)
        self.assertTrue(all("/users/me/" in url for url, _ in calls))

    def test_top_n_is_clamped_and_github_failures_are_a_502(self):
        c = self.client(repos=[raw(f"me/r{i}", stars=1) for i in range(15)])
        self.assertEqual(c.get("/pulse/dry-run?top_n=999").status_code, 200)
        down = TestClient(create_app(env={"REPO_PULSE_ACCOUNTS": "ghost"}, fetch=fake_fetch({"ghost": 404})))
        reply = down.get("/pulse/dry-run")
        self.assertEqual(reply.status_code, 502)
        self.assertIn("No GitHub account", reply.json()["detail"])


class AgentTests(unittest.TestCase):
    def test_tool_reports_missing_config_and_errors_as_data(self):
        from repo_pulse import agent

        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIn("REPO_PULSE_ACCOUNTS", agent.preview_repo_pulse()["error"])
        with mock.patch.dict(os.environ, {"REPO_PULSE_ACCOUNTS": "me"}, clear=True), mock.patch.object(agent, "run_pulse", side_effect=GitHubError("nope")):
            self.assertEqual(agent.preview_repo_pulse(), {"error": "nope"})

    def test_tool_returns_the_rendered_brief(self):
        from repo_pulse import agent

        fake = service.run_pulse(["me"], fetch=fake_fetch({"me": [raw("me/a")]}), now=NOW)
        with mock.patch.dict(os.environ, {"REPO_PULSE_ACCOUNTS": "me"}, clear=True), mock.patch.object(agent, "run_pulse", return_value=fake):
            self.assertIn("Repo Pulse for me", agent.preview_repo_pulse(3)["text"])

    def test_root_agent_exposes_the_tool_when_adk_is_installed(self):
        try:
            import google.adk  # noqa: F401
        except ImportError:
            self.skipTest("google-adk not installed")
        from repo_pulse import agent

        self.assertIsNotNone(agent.root_agent)
        self.assertEqual(agent.root_agent.name, "repo_pulse")
        self.assertIn(agent.preview_repo_pulse, agent.root_agent.tools)
        self.assertIn("Never claim to have sent", agent.root_agent.instruction)


if __name__ == "__main__":
    unittest.main(verbosity=1)
