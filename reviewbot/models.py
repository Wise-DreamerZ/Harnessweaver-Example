"""The task's typed input and output (``tasks.review.input`` and ``.output``)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["Finding", "Review", "ReviewRequest", "Severity"]


class ReviewRequest(BaseModel):
    """The pull-request webhook payload the bot is woken with.

    The PR's author writes the title and body, so the harness treats them as
    untrusted: the input guard checks them before the model sees them.
    """

    model_config = ConfigDict(extra="forbid")

    repo: str = Field(description="owner/name")
    number: int = Field(ge=1)
    title: str
    body: str = ""
    author: str


Severity = Literal["info", "minor", "major", "critical"]


class Finding(BaseModel):
    """One problem the reviewer found, pinned to a file and, ideally, a line."""

    model_config = ConfigDict(extra="forbid")

    file: str
    line: int | None = None
    severity: Severity = Field(
        description="critical: security hole or data loss; major: a bug that will hit "
        "production; minor: maintainability; info: a note"
    )
    message: str = Field(max_length=500)


class Review(BaseModel):
    """What the bot concludes. The app posts it; the model never posts it itself."""

    model_config = ConfigDict(extra="forbid")

    verdict: Literal["approve", "comment", "request_changes"]
    summary: str = Field(max_length=600)
    findings: list[Finding] = Field(default_factory=list[Finding])
