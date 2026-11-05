"""The ``approve`` task's handler: approval follows the final review, not the model.

The model can't call ``approve_pr`` (the ``review`` task doesn't offer it). Once
a review finishes, and so has passed ``validation.rules`` (no approval with a
major or critical finding), the app runs ``approve`` with that review. This
handler calls ``approve_pr`` only for an ``approve`` verdict, through the
governor like any tool call: the policy, ``reviewbot.protected_paths`` and the
manifest's maintainer approval all still apply. No model runs here
(``max_model_calls: 0``).

After a maintainer answers, the session runner runs this handler again from the
start; the approved call is recognized and passes without asking again.
"""

import harnessweaver as hw

from reviewbot.models import ApproveInput, ApproveOutcome

__all__ = ["approve_if_recommended"]


async def approve_if_recommended(s: hw.Session, ask: ApproveInput) -> ApproveOutcome:
    """Ask to approve the PR if, and only if, its review recommends it."""
    if ask.review.verdict != "approve":
        return ApproveOutcome(number=ask.number, approved=False)
    await s.tool("approve_pr", number=ask.number)
    return ApproveOutcome(number=ask.number, approved=True)
