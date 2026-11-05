"""Review the sample pull requests and show what the harness let through.

    HARNESSWEAVER_ENV=offline uv run python -m reviewbot.main          # all of them
    HARNESSWEAVER_ENV=offline uv run python -m reviewbot.main 106 --trace
    HARNESSWEAVER_ENV=offline uv run python -m reviewbot.main 106 --ask

Each review is one ``harness.run("review", request)`` call. When the bot asks
for something a person must allow (approving a PR, or a comment after it read
the private repo), the run waits and a maintainer answers. By default a
scripted maintainer answers; ``--ask`` lets you answer. Without
``HARNESSWEAVER_ENV`` the reviews go to Claude.
"""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Literal

import harnessweaver as hw
from harnessweaver.testing import render_trace

from reviewbot import github

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


async def review(harness: hw.Harness, number: int, *, ask: bool, show_trace: bool) -> None:
    """Review one pull request, answering what it waits for as a maintainer."""
    request = github.request_for(number)
    print(f"#{number} {request.title}  (by {request.author})")
    result = await harness.run("review", request, principal=triggered_by(request.author))
    print(f"  {describe(result)}")
    for _ in range(MAX_ANSWERS):
        approval = result.approval
        if approval is None:
            break
        print(f"    held: {held_call(approval)}")
        answer, why = await ask_maintainer(approval) if ask else scripted_maintainer(approval)
        verb = "allows it" if answer == "approve" else f"rejects it: {why}"
        print(f"  {MAINTAINER.id} ({MAINTAINER.roles[0]}) {verb}")
        result = await harness.approve(
            result.run_id, approval.approval_id, answer, approver=MAINTAINER, reason=why
        )
        print(f"  {describe(result)}")
    if result.cost_usd is not None:
        print(f"  cost: ${result.cost_usd:.6f}")
    if show_trace:
        print(render_trace(result))
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
