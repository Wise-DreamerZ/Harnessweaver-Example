"""The tools the reviewer may call. Their manifests in ``tools/`` govern every call:
the governor checks the schema, policy, the lethal trifecta, rate limits and
approvals before any of these functions runs.
"""

from typing import Any

from reviewbot import github

__all__ = ["approve_pr", "get_diff", "merge_pr", "post_comment", "read_file"]


def get_diff(number: int) -> dict[str, Any]:
    """Read a pull request's changed files and unified diff."""
    pull = github.PULLS.get(number)
    if pull is None:
        return {"number": number, "found": False}
    return {"number": number, "files": pull["files"], "diff": pull["diff"]}


def read_file(path: str) -> dict[str, Any]:
    """Read a file from the repository's base branch, for context around a change."""
    if ".." in path.split("/"):
        return {"path": path, "found": False}
    content = github.FILES.get(path)
    if content is None:
        return {"path": path, "found": False}
    return {"path": path, "content": content}


def post_comment(number: int, body: str, idempotency_key: str) -> dict[str, Any]:
    """Post a comment on a pull request.

    The governor passes ``idempotency_key``, so a call retried after a resume
    posts once.
    """
    for comment in github.COMMENTS:
        if comment["key"] == idempotency_key:
            return {"number": number, "posted": True, "duplicate": True}
    github.COMMENTS.append({"number": number, "body": body, "key": idempotency_key})
    return {"number": number, "posted": True}


def approve_pr(number: int, idempotency_key: str) -> dict[str, Any]:
    """Approve a pull request. Its manifest makes a maintainer confirm every call."""
    if not any(a["key"] == idempotency_key for a in github.APPROVALS):
        github.APPROVALS.append({"number": number, "key": idempotency_key})
    return {"number": number, "state": "approved"}


def merge_pr(number: int, idempotency_key: str) -> dict[str, Any]:
    """Merge a pull request. Registered, but no task offers it to the model."""
    if not any(m["key"] == idempotency_key for m in github.MERGES):
        github.MERGES.append({"number": number, "key": idempotency_key})
    return {"number": number, "state": "merged"}
