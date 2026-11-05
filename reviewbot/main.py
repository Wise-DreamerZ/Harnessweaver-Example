"""Review the sample pull requests and show what the harness let through.

    HARNESSWEAVER_ENV=offline uv run python -m reviewbot.main          # all of them
    HARNESSWEAVER_ENV=offline uv run python -m reviewbot.main 106 --trace

Each review is one ``harness.run("review", request)`` call. When the bot asks to
approve, the run waits; here a maintainer approves it, and the run resumes from
where it stopped. Without ``HARNESSWEAVER_ENV=offline`` the reviews go to Claude
(set ``ANTHROPIC_API_KEY``).
"""

import argparse
import asyncio
from pathlib import Path

import harnessweaver as hw
from harnessweaver.testing import render_trace

from reviewbot import github

SPEC = Path(__file__).resolve().parents[1] / "harness.yaml"
MAINTAINER = hw.Principal(id="mia", roles=("maintainer",))


def triggered_by(author: str) -> hw.Principal:
    """The principal a review runs as: the PR's author, with their role."""
    return hw.Principal(id=author, roles=github.ROLES.get(author, ("external",)))


def describe(result: hw.RunResult) -> str:
    """One line on how a run ended."""
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


SEVERITY = ["none", "info", "minor", "major", "critical"]


async def review(harness: hw.Harness, number: int, show_trace: bool) -> None:
    """Review one pull request, approving as a maintainer if the bot asks to."""
    request = github.request_for(number)
    print(f"#{number} {request.title}  (by {request.author})")
    result = await harness.run("review", request, principal=triggered_by(request.author))
    print(f"  {describe(result)}")
    if result.approval is not None:
        print(f"  {MAINTAINER.id} ({MAINTAINER.roles[0]}) approves the call")
        result = await harness.approve(
            result.run_id, result.approval.approval_id, approver=MAINTAINER
        )
        print(f"  {describe(result)}")
    if result.cost_usd is not None:
        print(f"  cost: ${result.cost_usd:.6f}")
    if show_trace:
        print(render_trace(result))
    print()


async def main(numbers: list[int] | None = None, show_trace: bool = False) -> None:
    """Review ``numbers`` (default: every sample PR), then show what reached GitHub."""
    harness = hw.load(SPEC)
    github.reset()
    for number in numbers or list(github.PULLS):
        await review(harness, number, show_trace)
    print("What reached GitHub:")
    print(f"  comments:  {[c['number'] for c in github.COMMENTS]}")
    print(f"  approvals: {[a['number'] for a in github.APPROVALS]}")
    print(f"  merges:    {[m['number'] for m in github.MERGES]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("numbers", nargs="*", type=int, help="PR numbers (default: all)")
    parser.add_argument("--trace", action="store_true", help="print each run's trace")
    args = parser.parse_args()
    unknown = sorted(set(args.numbers) - set(github.PULLS))
    if unknown:
        parser.error(f"no sample PR {unknown}; pick from {sorted(github.PULLS)}")
    asyncio.run(main(args.numbers, args.trace))
