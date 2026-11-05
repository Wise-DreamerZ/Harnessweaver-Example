"""The review bot's own plugin, loaded through ``plugins.local``.

``protected_paths`` is a rule a cel-lite policy can't express: the policy sees
the call's arguments (just a PR number), not the files the PR changes. A few
lines of Python can look them up, so this middleware runs on ``tool.before``
next to the built-in governor and blocks any approval or merge of a change to
CI workflows or CODEOWNERS. Those changes always need a person's full review.
"""

import harnessweaver as hw

from reviewbot import github

__all__ = ["plugin", "protected_paths"]

_GUARDED_TOOLS = frozenset({"approve_pr", "merge_pr"})


@hw.middleware(hooks=["tool.before"], band="app", fail_mode="closed", timeout="1s")
async def protected_paths(event: hw.ToolCallEvent, env: hw.Envelope) -> hw.Outcome | None:
    """Block the bot from approving or merging a PR that touches protected paths."""
    if event.call.name not in _GUARDED_TOOLS:
        return None
    touched = github.protected_files(event.call.arguments.get("number"))
    if not touched:
        return None
    return hw.Block(
        reason=f"the bot never approves changes to {', '.join(touched)}",
        code="protected_path",
    )


plugin = hw.Plugin(
    namespace="reviewbot",
    version="1.0.0",
    middleware=[protected_paths],
    description="The review bot's own controls.",
)
