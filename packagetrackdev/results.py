"""What one `check` run found, as data rather than as printed lines."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

COMPARED = "compared"
UNKNOWN_PACKAGE = "unknown_package"
UNPINNED = "unpinned"
UNPLACED_VERSION = "unplaced_version"
NOT_ANSWERED = "not_answered"

SERVER_UNREACHABLE = "server_unreachable"
SERVER_REJECTED = "server_rejected"
MALFORMED_ANSWER = "malformed_answer"
UNMATCHED_ANSWERS = "unmatched_answers"


@dataclass(slots=True)
class Requested:
    """One package as the dependency file spelled it, before any answer."""

    index: int
    name: str
    version: str
    parents: list[str] = field(default_factory=list)
    indirect: bool = False

    @property
    def direct(self) -> bool:
        return not self.parents and not self.indirect


@dataclass(slots=True)
class PackageResult:
    """One requested package and whatever the server could say about it."""

    requested: Requested
    comparison: str
    answered: bool = False
    name: str | None = None
    versions_behind: int | None = None
    latest: str | None = None
    latest_stable: str | None = None
    withdrawn: bool = False
    withdrawn_reason: str | None = None
    deprecated: bool = False
    deprecated_reason: str | None = None
    notes: list[dict] = field(default_factory=list)

    @property
    def behind(self) -> int:
        """The gap, or 0 when there is no gap and no claim to make."""
        return self.versions_behind or 0


@dataclass(slots=True)
class RunError:
    """Something that went wrong, named by a code."""

    code: str
    scope: dict[str, Any]
    message: str
    detail: str | None = None


@dataclass(slots=True)
class ProjectResult:
    """One dependency file, read and asked about."""

    ecosystem: str
    source: str
    packages: list[PackageResult] = field(default_factory=list)
    errors: list[RunError] = field(default_factory=list)
    skipped: int = 0
    note: str | None = None
