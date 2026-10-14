"""Command line:  python -m repo_pulse --accounts Sup3rMar10,Supp3r-Man

Dry run by default: reads GitHub, prints the brief, sends nothing and saves nothing.
"""

import argparse
import json
import os
import sys

from .github import GitHubError
from .service import parse_accounts, run_pulse


def main(argv=None):
    parser = argparse.ArgumentParser(prog="repo_pulse", description="A briefing on your GitHub accounts. Dry run unless told otherwise.")
    parser.add_argument("--accounts", default=os.environ.get("REPO_PULSE_ACCOUNTS", ""), help="Comma-separated GitHub accounts (or REPO_PULSE_ACCOUNTS)")
    parser.add_argument("--top", type=int, default=5, help="How many changed repos to list, 1 to 10")
    parser.add_argument("--format", choices=["text", "markdown", "html", "json"], default="text")
    parser.add_argument("--state", default=os.environ.get("REPO_PULSE_STATE"), help="State file that remembers the last snapshot")
    parser.add_argument("--save-state", action="store_true", help="Save this snapshot as the new baseline")
    parser.add_argument("--send", action="store_true", help="Deliver the brief through the configured webhook")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    accounts = parse_accounts(args.accounts)
    if not accounts:
        print("error: no accounts. Use --accounts or set REPO_PULSE_ACCOUNTS.", file=sys.stderr)
        return 2
    try:
        result = run_pulse(
            accounts,
            token=os.environ.get("GITHUB_TOKEN"),
            state_path=args.state,
            top_n=args.top,
            deliver_brief=args.send,
            save_state=args.save_state,
        )
    except GitHubError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps({"delivery": result["delivery"], "state_saved": result["state_saved"], "brief": result["brief"], "rendered": result["rendered"]}, indent=2))
    else:
        print(result["rendered"][args.format])
    if args.send or args.save_state:
        print(f"\n[delivery: {result['delivery']['status']}. {result['delivery']['detail']} State saved: {result['state_saved']}]", file=sys.stderr)
    return 1 if args.send and not result["delivery"]["sent"] else 0


if __name__ == "__main__":
    sys.exit(main())
