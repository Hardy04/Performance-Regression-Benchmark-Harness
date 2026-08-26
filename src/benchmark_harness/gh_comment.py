"""GitHub PR comment poster: creates or updates the benchmark report comment."""

from __future__ import annotations

import os
from pathlib import Path

import requests

_MARKER = "<!-- benchmark-harness-report -->"
_API_BASE = "https://api.github.com"


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _find_existing_comment(
    token: str,
    repo: str,
    pr_number: int,
) -> int | None:
    """Return the comment ID of our existing report comment, or None."""
    url = f"{_API_BASE}/repos/{repo}/issues/{pr_number}/comments"
    params: dict = {"per_page": 100}
    while url:
        resp = requests.get(url, headers=_headers(token), params=params, timeout=15)
        resp.raise_for_status()
        for comment in resp.json():
            if _MARKER in comment.get("body", ""):
                return int(comment["id"])
        # Follow pagination
        url = resp.links.get("next", {}).get("url")
        params = {}
    return None


def post_or_update_comment(
    markdown_path: Path,
    repo: str,
    pr_number: int,
    token: str | None = None,
) -> str:
    """
    Post a new PR comment or update the existing one for this harness.

    Args:
        markdown_path: Path to the Markdown report file.
        repo:          GitHub repo in "owner/name" format.
        pr_number:     Pull request number.
        token:         GitHub token (defaults to GITHUB_TOKEN env var).

    Returns:
        The HTML URL of the created/updated comment.
    """
    token = token or os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise EnvironmentError(
            "GitHub token not found. Set GITHUB_TOKEN or pass token= explicitly."
        )

    body = markdown_path.read_text(encoding="utf-8")

    comment_id = _find_existing_comment(token, repo, pr_number)

    if comment_id:
        url = f"{_API_BASE}/repos/{repo}/issues/comments/{comment_id}"
        resp = requests.patch(url, headers=_headers(token), json={"body": body}, timeout=15)
        resp.raise_for_status()
    else:
        url = f"{_API_BASE}/repos/{repo}/issues/{pr_number}/comments"
        resp = requests.post(url, headers=_headers(token), json={"body": body}, timeout=15)
        resp.raise_for_status()

    return str(resp.json().get("html_url", ""))
