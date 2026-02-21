#!/usr/bin/env python3
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, Optional, Tuple

OFFICIAL_GITHUB_HOST = "github.com"
OFFICIAL_GITHUB_URL = f"https://{OFFICIAL_GITHUB_HOST}"
PR_URL_RE = re.compile(
    rf"^{re.escape(OFFICIAL_GITHUB_URL)}/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)(?:/)?$"
)

QUERY = """
query($owner: String!, $repo: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      number
      title
      url
      reviewThreads(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          isResolved
          isOutdated
          path
          line
          originalLine
          startLine
          originalStartLine
          subjectType
          comments(first: 100) {
            nodes {
              id
              databaseId
              bodyText
              createdAt
              author { login }
              url
              resourcePath
            }
          }
        }
      }
    }
  }
}
"""


def parse_repo_input(repo_input: str) -> Tuple[str, str]:
    if "/" not in repo_input:
        raise ValueError("--repo must be in the form owner/name")
    owner, repo = repo_input.split("/", 1)
    if not owner or not repo:
        raise ValueError("--repo must be in the form owner/name")
    return owner, repo


def parse_pr_url(pr_input: str) -> Optional[Tuple[str, str, int]]:
    match = PR_URL_RE.match(pr_input)
    if not match:
        return None
    return match.group("owner"), match.group("repo"), int(match.group("number"))


def build_gh_env() -> Dict[str, str]:
    env = os.environ.copy()
    env["GH_HOST"] = OFFICIAL_GITHUB_HOST
    env.setdefault("GH_PAGER", "cat")
    return env


def parse_pr_input(pr_input: Optional[str], repo_input: Optional[str], number_input: Optional[int]) -> Tuple[str, str, int]:
    owner = None
    repo = None
    number = None

    if pr_input:
        parsed = parse_pr_url(pr_input)
        if parsed:
            owner, repo, number = parsed
        else:
            raise ValueError(
                f"PR URL must match {OFFICIAL_GITHUB_URL}/owner/repo/pull/<number>."
            )

    if number is None and number_input is not None:
        raise ValueError("PR number alone is not allowed. Provide a full PR URL.")

    if owner is None or repo is None:
        if repo_input:
            owner, repo = parse_repo_input(repo_input)

    if owner is None or repo is None or number is None:
        raise ValueError(
            "PR not fully specified. Provide --pr <url> (must be a full GitHub PR URL)."
        )

    return owner, repo, number


def graphql_request(owner: str, repo: str, number: int, cursor: Optional[str], query: str) -> Dict[str, Any]:
    gh_path = shutil.which("gh")
    if not gh_path:
        raise RuntimeError("gh CLI not found in PATH. Install GitHub CLI and authenticate.")

    cmd = [
        gh_path,
        "api",
        "graphql",
        "-F",
        f"owner={owner}",
        "-F",
        f"repo={repo}",
        "-F",
        f"number={number}",
        "-F",
        f"cursor={cursor if cursor is not None else 'null'}",
        "-f",
        f"query={query}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, env=build_gh_env())
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh api graphql failed")
    return json.loads(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch unresolved PR review threads from GitHub GraphQL.")
    parser.add_argument("--pr", help="PR URL (full https://github.com/OWNER/REPO/pull/NUMBER)")
    parser.add_argument("--repo", help="Repository in owner/name format")
    parser.add_argument("--number", type=int, help="PR number (forbidden; use --pr URL instead)")
    parser.add_argument("--out", help="Output JSON path")
    parser.add_argument("--include-outdated", action="store_true", help="Include outdated threads")
    parser.add_argument("--include-resolved", action="store_true", help="Include resolved threads")
    args = parser.parse_args()

    try:
        owner, repo, number = parse_pr_input(args.pr, args.repo, args.number)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    threads = []
    cursor = None
    pr_info = None

    while True:
        try:
            response = graphql_request(owner, repo, number, cursor, QUERY)
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        if "errors" in response:
            print("ERROR: GraphQL query failed:", file=sys.stderr)
            print(json.dumps(response["errors"], indent=2), file=sys.stderr)
            return 1

        repo_data = response.get("data", {}).get("repository")
        if not repo_data or not repo_data.get("pullRequest"):
            print("ERROR: PR not found or access denied.", file=sys.stderr)
            return 1

        pr_info = repo_data["pullRequest"]
        connection = pr_info["reviewThreads"]
        nodes = connection.get("nodes") or []

        for thread in nodes:
            if not args.include_resolved and thread.get("isResolved"):
                continue
            if not args.include_outdated and thread.get("isOutdated"):
                continue
            threads.append(thread)

        page_info = connection.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")

    timestamp = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    output = {
        "repository": f"{owner}/{repo}",
        "pull_request": {
            "number": pr_info["number"],
            "title": pr_info["title"],
            "url": pr_info["url"],
        },
        "generated_at": timestamp,
        "filters": {
            "include_resolved": bool(args.include_resolved),
            "include_outdated": bool(args.include_outdated),
        },
        "threads": threads,
    }

    default_out = f"/tmp/gh-pr-unresolved-comments-{owner}-{repo}-{number}.json"
    out_path = args.out or default_out
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(output, handle, indent=2)

    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
