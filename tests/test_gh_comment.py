"""Tests for the GitHub PR comment poster (requests mocked)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from benchmark_harness.gh_comment import _find_existing_comment, post_or_update_comment

_MARKER = "<!-- benchmark-harness-report -->"
_TOKEN = "ghp_fake_token"
_REPO = "owner/repo"
_PR = 7


def _mock_response(json_data: object, status_code: int = 200, links: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.links = links or {}
    resp.raise_for_status = MagicMock()
    return resp


# --- _find_existing_comment ---

def test_find_returns_none_when_no_comments():
    with patch("benchmark_harness.gh_comment.requests.get") as mock_get:
        mock_get.return_value = _mock_response([])
        result = _find_existing_comment(_TOKEN, _REPO, _PR)
    assert result is None


def test_find_returns_id_when_marker_present():
    comments = [
        {"id": 1, "body": "unrelated comment"},
        {"id": 42, "body": f"{_MARKER}\n## Report"},
    ]
    with patch("benchmark_harness.gh_comment.requests.get") as mock_get:
        mock_get.return_value = _mock_response(comments)
        result = _find_existing_comment(_TOKEN, _REPO, _PR)
    assert result == 42


def test_find_returns_none_when_marker_absent():
    comments = [{"id": 10, "body": "just a review comment"}]
    with patch("benchmark_harness.gh_comment.requests.get") as mock_get:
        mock_get.return_value = _mock_response(comments)
        result = _find_existing_comment(_TOKEN, _REPO, _PR)
    assert result is None


def test_find_follows_pagination():
    page1 = [{"id": 1, "body": "no marker"}]
    page2 = [{"id": 99, "body": f"{_MARKER}\n## Report"}]

    resp1 = _mock_response(page1, links={"next": {"url": "https://api.github.com/page2"}})
    resp2 = _mock_response(page2)

    with patch("benchmark_harness.gh_comment.requests.get") as mock_get:
        mock_get.side_effect = [resp1, resp2]
        result = _find_existing_comment(_TOKEN, _REPO, _PR)
    assert result == 99
    assert mock_get.call_count == 2


# --- post_or_update_comment ---

def test_creates_new_comment_when_none_exists(tmp_path: Path):
    report = tmp_path / "report.md"
    report.write_text(f"{_MARKER}\n## Report", encoding="utf-8")

    get_resp = _mock_response([])  # no existing comment
    post_resp = _mock_response({"html_url": "https://github.com/owner/repo/issues/7#issuecomment-1"})

    with patch("benchmark_harness.gh_comment.requests.get", return_value=get_resp), \
         patch("benchmark_harness.gh_comment.requests.post", return_value=post_resp) as mock_post, \
         patch("benchmark_harness.gh_comment.requests.patch") as mock_patch:

        url = post_or_update_comment(report, repo=_REPO, pr_number=_PR, token=_TOKEN)

    mock_post.assert_called_once()
    mock_patch.assert_not_called()
    assert "issuecomment" in url


def test_updates_existing_comment_when_marker_found(tmp_path: Path):
    report = tmp_path / "report.md"
    report.write_text(f"{_MARKER}\n## Report v2", encoding="utf-8")

    existing = [{"id": 55, "body": f"{_MARKER}\n## Report v1"}]
    get_resp = _mock_response(existing)
    patch_resp = _mock_response({"html_url": "https://github.com/owner/repo/issues/7#issuecomment-55"})

    with patch("benchmark_harness.gh_comment.requests.get", return_value=get_resp), \
         patch("benchmark_harness.gh_comment.requests.patch", return_value=patch_resp) as mock_patch, \
         patch("benchmark_harness.gh_comment.requests.post") as mock_post:

        url = post_or_update_comment(report, repo=_REPO, pr_number=_PR, token=_TOKEN)

    mock_patch.assert_called_once()
    mock_post.assert_not_called()
    assert "55" in url


def test_raises_when_no_token(tmp_path: Path):
    report = tmp_path / "report.md"
    report.write_text("content", encoding="utf-8")

    with patch.dict("os.environ", {}, clear=True):
        # Remove GITHUB_TOKEN if present in env
        import os
        os.environ.pop("GITHUB_TOKEN", None)
        with pytest.raises(EnvironmentError, match="GitHub token not found"):
            post_or_update_comment(report, repo=_REPO, pr_number=_PR, token=None)


def test_reads_token_from_env(tmp_path: Path):
    report = tmp_path / "report.md"
    report.write_text(f"{_MARKER}", encoding="utf-8")

    get_resp = _mock_response([])
    post_resp = _mock_response({"html_url": "https://github.com/owner/repo/issues/7#issuecomment-2"})

    import os
    with patch.dict(os.environ, {"GITHUB_TOKEN": "env_token"}), \
         patch("benchmark_harness.gh_comment.requests.get", return_value=get_resp), \
         patch("benchmark_harness.gh_comment.requests.post", return_value=post_resp) as mock_post:

        post_or_update_comment(report, repo=_REPO, pr_number=_PR, token=None)

    # Verify the env token was used in the Authorization header
    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer env_token"
