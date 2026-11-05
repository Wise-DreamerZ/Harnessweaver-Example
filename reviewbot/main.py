"""Review the sample pull requests and show what the harness let through.

    HARNESSWEAVER_ENV=offline uv run python -m reviewbot.main          # all of them
    HARNESSWEAVER_ENV=offline uv run python -m reviewbot.main 106 --trace
    HARNESSWEAVER_ENV=offline uv run python -m reviewbot.main 106 --ask

Each pull request takes up to two runs. ``harness.run("review", request)`` has
the model review it. If the finished review recommends approval, and so passed
the business rules, ``harness.run("approve", ...)`` asks to approve it; no model
runs there. When a run asks for something a person must allow (an approval, or
a comment after the bot read the private repo), it waits and a maintainer
answers. By default a scripted maintainer answers; ``--ask`` lets you answer.
Without ``HARNESSWEAVER_ENV`` the reviews go to Claude.
"""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Literal

import harnessweaver as hw
from harnessweaver.testing import render_trace

from reviewbot import github
from reviewbot.models import ApproveInput, Review

SPEC = Path(__file__).resolve().parents[1] / "harness.yaml"
MAINTAINER = hw.Principal(id="mia", roles=("maintainer",))
MAX_ANSWERS = 5
"""How many held calls one review may ask about before the demo gives up."""

SEVERITY = ["none", "info", "minor", "major", "critical"]

Answer = Literal["approve", "reject"]


def triggered_by(author: str) -> hw.Principal:
    """The principal a review runs as: the PR's author, with their role."""
    return hw.Principal(id=author, roles=github.ROLES.get(author, ("external",)))


def describe(result: hw.RunResult) -> str:
    """One line on how a run ended, or what it waits for."""
    status = result.status.value
    if result.approval is not None:
        return f"{status}: {result.approval.reason} (asks a {result.approval.approver_role})"
    if result.error is not None:
        code = result.error.details.get("code", "")
        return f"{status} [{code}]: {result.error.message}"
    review = result.output if isinstance(result.output, dict) else {}
    if "approved" in review:  # the approve task's ApproveOutcome
        return f"{status}: {'approved' if review['approved'] else 'not approved'}"
    findings = review.get("findings") or []
    worst = max((f["severity"] for f in findings), key=SEVERITY.index, default="none")
    return f"{status}: {review.get('verdict')} ({len(findings)} finding(s), worst: {worst})"


def held_call(approval: hw.ApprovalRequest) -> str:
    """The call a person is asked to allow, as they would see it."""
    if approval.call is None:
        return "(no tool call)"
    return f"{approval.call.name} {json.dumps(approval.call.arguments, ensure_ascii=False)}"


def quotes_private_config(text: str) -> bool:
    """Whether ``text`` repeats a setting from the private ``config/`` files."""
    settings = [
        line
        for path, content in github.FILES.items()
        if path.startswith("config/")
        for line in content.splitlines()
        if line and not line.startswith("#")
    ]
    return any(setting in text for setting in settings)


def scripted_maintainer(approval: hw.ApprovalRequest) -> tuple[Answer, str | None]:
    """Stands in for a person reading the held call: allows it unless it would post
    private config."""
    body = approval.call.arguments.get("body") if approval.call is not None else None
    if isinstance(body, str) and quotes_private_config(body):
        return "reject", "the comment quotes the private deploy config"
    return "approve", None


async def ask_maintainer(approval: hw.ApprovalRequest) -> tuple[Answer, str | None]:
    """Ask the person at the terminal."""
    reply = await asyncio.to_thread(input, f"  allow it as {MAINTAINER.id}? [y/N] ")
    if reply.strip().lower() in ("y", "yes"):
        return "approve", None
    return "reject", "rejected at the terminal"


async def answer_held(harness: hw.Harness, result: hw.RunResult, *, ask: bool) -> hw.RunResult:
    """Answer what a run waits for, as a maintainer, until it ends."""
    for _ in range(MAX_ANSWERS):
        approval = result.approval
        if approval is None:
            break
        print(f"    held: {held_call(approval)}")
        answer, why = await ask_maintainer(approval) if ask else scripted_maintainer(approval)
        verb = "allows it" if answer == "approve" else f"rejects it: {why}"
        print(f"    {MAINTAINER.id} ({MAINTAINER.roles[0]}) {verb}")
        result = await harness.approve(
            result.run_id, approval.approval_id, answer, approver=MAINTAINER, reason=why
        )
        print(f"    {describe(result)}")
    return result


def recommends_approval(result: hw.RunResult) -> bool:
    """Whether a finished review run's (validated) review says approve."""
    return result.ok and isinstance(result.output, dict) and result.output["verdict"] == "approve"


async def review(harness: hw.Harness, number: int, *, ask: bool, show_trace: bool) -> None:
    """Review one pull request; if the review recommends it, ask to approve it."""
    request = github.request_for(number)
    principal = triggered_by(request.author)
    print(f"#{number} {request.title}  (by {request.author})")
    result = await harness.run("review", request, principal=principal)
    print(f"  review:  {describe(result)}")
    runs = [await answer_held(harness, result, ask=ask)]
    if recommends_approval(runs[0]):
        ask_for = ApproveInput(
            repo=request.repo, number=number, review=Review.model_validate(runs[0].output)
        )
        result = await harness.run("approve", ask_for, principal=principal)
        print(f"  approve: {describe(result)}")
        runs.append(await answer_held(harness, result, ask=ask))
    costs = [r.cost_usd for r in runs if r.cost_usd is not None]
    if costs:
        print(f"  cost: ${sum(costs):.6f}")
    if show_trace:
        for run in runs:
            print(f"  -- {run.task} --")
            print(render_trace(run))
    print()


async def main(
    numbers: list[int] | None = None, *, ask: bool = False, show_trace: bool = False
) -> None:
    """Review ``numbers`` (default: every sample PR), then show what reached GitHub."""
    harness = hw.load(SPEC)
    github.reset()
    for number in numbers or list(github.PULLS):
        await review(harness, number, ask=ask, show_trace=show_trace)
    print("What reached GitHub:")
    print(f"  comments:  {[(c['number'], c['body']) for c in github.COMMENTS]}")
    print(f"  approvals: {[a['number'] for a in github.APPROVALS]}")
    print(f"  merges:    {[m['number'] for m in github.MERGES]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("numbers", nargs="*", type=int, help="PR numbers (default: all)")
    parser.add_argument("--ask", action="store_true", help="answer held calls yourself")
    parser.add_argument("--trace", action="store_true", help="print each run's trace")
    args = parser.parse_args()
    unknown = sorted(set(args.numbers) - set(github.PULLS))
    if unknown:
        parser.error(f"no sample PR {unknown}; pick from {sorted(github.PULLS)}")
    asyncio.run(main(args.numbers, ask=args.ask, show_trace=args.trace))
