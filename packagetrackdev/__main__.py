"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import httpx

from packagetrackdev import config

from packagetrackdev.excerpt import NOTES_SHOWN
from packagetrackdev.excerpt import clip as _clip
from packagetrackdev.excerpt import summarise as _summarise
from packagetrackdev.lockfiles import (
    LOCKFILES,
    Dependency,
    Project,
    find,
    read,
)
from packagetrackdev.lockfiles import (
    ecosystems as lockfile_ecosystems,
)
from packagetrackdev.results import (
    COMPARED,
    MALFORMED_ANSWER,
    NOT_ANSWERED,
    SERVER_REJECTED,
    SERVER_UNREACHABLE,
    UNKNOWN_PACKAGE,
    UNMATCHED_ANSWERS,
    UNPINNED,
    UNPLACED_VERSION,
    PackageResult,
    ProjectResult,
    Requested,
    RunError,
)

REQUEST_TIMEOUT = 60.0


def _user_agent() -> dict[str, str]:
    """Return the User-Agent header."""
    return {"User-Agent": f"packagetrackdev/{installed_version()}"}


REASON_CHARS = 300


def response_reason(response: httpx.Response) -> str | None:
    """Extract a one-line reason from an error response, if any."""
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = response.text
    if detail is not None and not isinstance(detail, str):
        detail = json.dumps(detail)
    text = " ".join((detail or "").split())
    if len(text) > REASON_CHARS:
        text = text[:REASON_CHARS].rstrip() + "..."
    return text or None


def http_failure(exc: httpx.HTTPError, server: str) -> str:
    """Describe a failed request in one line."""
    if not isinstance(exc, httpx.HTTPStatusError):
        return f"could not reach {server}: {exc}"
    response = exc.response
    reason = response_reason(response)
    if response.status_code == 401:
        text = f"{server} rejected the API key (HTTP 401)"
        return f"{text}: {reason}" if reason else text
    return (
        f"{server} answered HTTP {response.status_code}: "
        f"{reason or response.reason_phrase or 'no reason given'}"
    )


KEY_HOWTO = (
    "  create one at {server}/app/keys, then either\n"
    "    export PACKAGETRACK_API_KEY=pkgt_...\n"
    "  or run: packagetrackdev login --api-key pkgt_..."
)


CHUNK = 300


def collect(project: Path, ecosystem: str | None) -> list[Project]:
    """Read every supported dependency file in the project."""
    found = []
    for eco, path in find(project):
        if ecosystem and eco != ecosystem:
            continue
        parsed = read(eco, path)
        if parsed:
            found.append(parsed)
    return found


def payload(ecosystem: str, packages: list[Dependency]) -> dict:
    """Build the request body for `check`."""
    return {
        "ecosystem": ecosystem,
        "packages": [{"name": p.name, "version": p.version} for p in packages],
    }


def snapshot_payload(project: Project) -> dict:
    """Build the request body for `push`."""
    return {
        "ecosystem": project.ecosystem,
        "source": project.source,
        "packages": [
            {
                "name": d.name,
                "version": d.version,
                "parents": d.parents[:20],
                "indirect": d.indirect,
            }
            for d in project.dependencies
        ],
    }


def push(server: str, api_key: str, name: str, project: Project) -> dict:
    """Upload one project's dependency set."""
    url = f"{server.rstrip('/')}/api/projects/{name}/snapshot"
    with httpx.Client(timeout=REQUEST_TIMEOUT, headers=_user_agent()) as client:
        response = client.post(
            url,
            json=snapshot_payload(project),
            headers={"Authorization": f"Bearer {api_key}"},
        )
        response.raise_for_status()
        return response.json()


def project_name(project: Project, given: str | None, folder: Path, many: bool) -> str:
    """Return the project name to use on the server."""
    base = given or re.sub(r"[^A-Za-z0-9._-]+", "-", folder.resolve().name).strip("-")
    base = base or "project"
    return f"{base}-{project.ecosystem}" if many and not given else base


def _flagged_block(heading: str, packages: list[PackageResult], attr: str) -> None:
    """Print one "these installed versions carry a flag" list.

    Withdrawn and deprecated read the same way -- name, whose dependency it
    is, what the registry said -- and differ only in the heading and in which
    reason is printed. One loop so the two lists cannot drift apart in
    wording; the ordering and the sentences around them are the caller's.
    """
    print(heading)
    for pkg in packages:
        reason = (getattr(pkg, attr) or "no reason given").strip()
        owners = pkg.requested.parents
        if owners:
            via = f"  (pulled in by {', '.join(owners[:3])})"
        elif not pkg.requested.direct:
            via = "  (indirect, this file does not record what requires it)"
        else:
            via = "  (yours)"
        print(f"  {pkg.name} {pkg.requested.version}{via}")
        print(f"      {_clip(reason)}")
    print()


def report(result: ProjectResult, show_all: bool) -> None:
    """Print the report for one project."""
    own = [p for p in result.packages if p.requested.direct]
    direct = [p for p in own if p.behind > 0]
    withdrawn = [p for p in result.packages if p.withdrawn]
    deprecated = [p for p in result.packages if p.deprecated]
    own_withdrawn = [p for p in own if p.withdrawn and p.behind == 0]
    unknown = [p for p in result.packages if p.comparison == UNKNOWN_PACKAGE]
    unpinned = [p for p in result.packages if p.comparison == UNPINNED]
    unplaced = [p for p in result.packages if p.comparison == UNPLACED_VERSION]

    print(
        f"\n{result.source}: {sum(1 for p in result.packages if p.answered)} "
        f"packages, {len(own)} of them yours.\n"
    )
    if result.note:
        print(f"{result.note}\n")
    if unpinned:
        one = len(unpinned) == 1
        print(
            f"{len(unpinned)} {'is a range' if one else 'are ranges'} rather than "
            f"{'a version' if one else 'versions'}, so how far behind "
            f"{'it is' if one else 'they are'} depends on when you last built."
        )
        for pkg in unpinned[:8]:
            newest = pkg.latest_stable
            print(
                f"  {pkg.requested.name}  newest release: {newest or 'unknown to us'}"
            )
        if len(unpinned) > 8:
            print(f"  ...and {len(unpinned) - 8} more")
        print()

    if unplaced:
        one = len(unplaced) == 1
        print(
            f"{len(unplaced)} installed "
            f"{'version is not one' if one else 'versions are not ones'} the "
            f"registry published, so we could not say how far behind "
            f"{'it is' if one else 'they are'}."
        )
        for pkg in unplaced[:8]:
            installed = pkg.requested.version or "no version recorded"
            print(f"  {pkg.name or pkg.requested.name}  installed: {installed}")
        if len(unplaced) > 8:
            print(f"  ...and {len(unplaced) - 8} more")
        print()

    if withdrawn:
        _flagged_block(
            "Withdrawn versions in this build:", withdrawn, "withdrawn_reason"
        )

    if deprecated:
        _flagged_block(
            "Deprecated versions in this build:", deprecated, "deprecated_reason"
        )

    if direct:
        print("Your dependencies, behind:")
        for pkg in sorted(direct, key=lambda p: -p.behind):
            print(
                f"\n{pkg.name} {pkg.requested.version} -> {pkg.latest_stable}"
                f"   {pkg.versions_behind} behind"
            )
            for note in pkg.notes[:NOTES_SHOWN]:
                print(f"  {note['version']}")
                for line in _summarise(note["body"]):
                    print(f"    {line}")
    elif all(p.comparison == COMPARED for p in own):
        if not withdrawn:
            print("Your own dependencies are all current.")
        elif own_withdrawn:
            one = len(own_withdrawn) == 1
            names = ", ".join(p.name or p.requested.name for p in own_withdrawn)
            print(
                f"{names} {'is' if one else 'are'} withdrawn with no newer "
                f"release to move to. Your other direct dependencies have no "
                f"version gap."
            )
        else:
            print("Your own direct dependencies have no version gap.")
    else:
        unmeasured = sum(1 for p in own if p.comparison != COMPARED)
        print(
            f"None of your own dependencies came back behind, and "
            f"{unmeasured} of them could not be compared."
        )

    behind_indirect = sum(
        1 for p in result.packages if p.behind > 0 and not p.requested.direct
    )
    if behind_indirect:
        print(
            f"\n{behind_indirect} packages you did not ask for are also behind. "
            "They come with the ones above and follow when those are updated."
        )

    if show_all and unknown:
        print("\nNot in the archive (we track the most-depended-on per registry):")
        print("  " + ", ".join(p.requested.name for p in unknown[:40]))


def requested_for(project: Project) -> list[Requested]:
    """Number the project's dependencies, so an answer has something to land on."""
    return [
        Requested(
            index=i,
            name=d.name,
            version=d.version,
            parents=list(d.parents),
            indirect=d.indirect,
        )
        for i, d in enumerate(project.dependencies)
    ]


def state_for(requested: Requested, row: dict) -> PackageResult:
    """Turn one answer row into a result, and name what it could not say."""
    result = PackageResult(
        requested=requested,
        comparison=COMPARED,
        answered=True,
        name=row.get("name") or requested.name,
        latest=row.get("latest"),
        latest_stable=row.get("latest_stable"),
        withdrawn=bool(row.get("installed_yanked")),
        withdrawn_reason=row.get("installed_yanked_reason"),
        deprecated=bool(row.get("installed_deprecated")),
        deprecated_reason=row.get("installed_deprecated_reason"),
        notes=list(row.get("notes") or []),
    )
    behind = row.get("versions_behind")
    placed = row.get("installed_known")
    if placed is None:
        placed = behind is not None

    if not requested.version:
        result.comparison = UNPINNED
    elif not row.get("known"):
        result.comparison = UNKNOWN_PACKAGE
    elif not placed or behind is None:
        result.comparison = UNPLACED_VERSION
    else:
        result.versions_behind = int(behind)
    return result


def place(batch: list[Requested], rows: list[dict]) -> tuple[list[PackageResult], int]:
    """Tie each answer to the request it belongs to; return what would not tie."""
    if len(rows) == len(batch) and all(
        str(row.get("installed", "")) == req.version
        for req, row in zip(batch, rows, strict=True)
    ):
        return [state_for(req, row) for req, row in zip(batch, rows, strict=True)], 0

    spare: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        key = (str(row.get("name", "")), str(row.get("installed", "")))
        spare.setdefault(key, []).append(row)

    placed = []
    for req in batch:
        for key in ((req.name, req.version), (req.name.casefold(), req.version)):
            if spare.get(key):
                placed.append(state_for(req, spare[key].pop(0)))
                break
    return placed, sum(len(rest) for rest in spare.values())


def query(server: str, project: Project) -> ProjectResult:
    """Ask the server about one project, keeping whatever answers arrive."""
    url = f"{server.rstrip('/')}/api/status"
    batches = requested_for(project)
    result = ProjectResult(
        ecosystem=project.ecosystem,
        source=project.source,
        skipped=project.skipped,
        note=project.note,
        packages=[PackageResult(requested=r, comparison=NOT_ANSWERED) for r in batches],
    )

    with httpx.Client(timeout=REQUEST_TIMEOUT, headers=_user_agent()) as client:
        for number, start in enumerate(range(0, len(batches), CHUNK)):
            batch = batches[start : start + CHUNK]
            scope = {
                "source": project.source,
                "ecosystem": project.ecosystem,
                "batch": {"number": number, "packages": len(batch)},
            }
            try:
                response = client.post(url, json=payload(project.ecosystem, batch))
                response.raise_for_status()
                rows = response.json().get("packages") or []
            except httpx.HTTPError as exc:
                result.errors.append(request_error(exc, server, scope))
                continue
            except ValueError:
                result.errors.append(
                    RunError(
                        code=MALFORMED_ANSWER,
                        scope=scope,
                        message="the server's answer could not be read",
                        detail=f"{server} answered with something that is not JSON",
                    )
                )
                continue

            answers, unmatched = place(batch, rows)
            for answer in answers:
                result.packages[answer.requested.index] = answer
            if unmatched:
                result.errors.append(
                    RunError(
                        code=UNMATCHED_ANSWERS,
                        scope=scope,
                        message=(
                            f"{unmatched} answers could not be matched to a "
                            f"requested package"
                        ),
                        detail=(
                            f"{server} answered for {unmatched} packages that "
                            f"were not asked about; they were ignored"
                        ),
                    )
                )

    return result


def request_error(exc: httpx.HTTPError, server: str, scope: dict) -> RunError:
    """Describe a failed request: a code to branch on, a sentence for a person."""
    detail = http_failure(exc, server)
    if not isinstance(exc, httpx.HTTPStatusError):
        return RunError(
            code=SERVER_UNREACHABLE,
            scope=scope,
            message="the server could not be reached",
            detail=detail,
        )
    return RunError(
        code=SERVER_REJECTED,
        scope={**scope, "http_status": exc.response.status_code},
        message=f"the server answered HTTP {exc.response.status_code}",
        detail=detail,
    )


def _projects_or_exit(folder: Path, ecosystem: str | None) -> list[Project]:
    projects = collect(folder, ecosystem)
    if projects:
        return projects
    wanted = ", ".join(sorted({name for _, name in LOCKFILES}))
    raise SystemExit(
        f"no lock file in {folder}\n"
        f"  looked for: {wanted}\n"
        f"  a lock file is what your build installs; without one we would be\n"
        f"  guessing at versions and blind to transitive dependencies."
    )


def cmd_check(args: argparse.Namespace) -> int:
    """Run `check`."""
    settings = config.load(server=args.server)
    projects = _projects_or_exit(args.project, args.ecosystem)

    if args.dry_run:
        print(
            json.dumps(
                [payload(p.ecosystem, p.dependencies) for p in projects], indent=2
            )
        )
        return 0

    for project in projects:
        result = query(settings.server, project)
        if result.errors:
            print(f"error: {result.errors[0].detail}", file=sys.stderr)
            return 2
        report(result, show_all=args.all)
    return 0


def cmd_push(args: argparse.Namespace) -> int:
    """Run `push`."""
    settings = config.load(api_key=args.api_key, server=args.server)
    projects = _projects_or_exit(args.project, args.ecosystem)

    if args.dry_run:
        print(json.dumps([snapshot_payload(p) for p in projects], indent=2))
        return 0

    if not settings.api_key:
        print(
            "error: no API key.\n" + KEY_HOWTO.format(server=settings.server),
            file=sys.stderr,
        )
        return 2

    many = len(projects) > 1
    broke_a_rule = False
    for project in projects:
        name = project_name(project, args.name, args.project, many)
        try:
            result = push(settings.server, settings.api_key, name, project)
        except httpx.HTTPError as exc:
            print(f"error: {http_failure(exc, settings.server)}", file=sys.stderr)
            if (
                isinstance(exc, httpx.HTTPStatusError)
                and exc.response.status_code == 401
            ):
                print(KEY_HOWTO.format(server=settings.server), file=sys.stderr)
            return 2

        created = result.get("created") is True
        bits = [f"{result['stored']} packages from {project.source}"]
        if created:
            bits.insert(0, "new project")
        if result.get("unchanged") is True:
            bits.append("no change since the last push")
        if result["withdrawn"]:
            bits.append(f"{result['withdrawn']} withdrawn")
        not_compared = result.get("not_compared")
        looking_up = result.get("being_looked_up") or 0
        unpinned = result.get("unpinned") or 0
        if (
            not_compared is not None
            and result["stored"]
            and not_compared + unpinned >= result["stored"]
        ):
            bits.append("none compared yet" if looking_up else "none compared")
        else:
            bits.append(f"{result['behind']} of yours behind")
        if unpinned:
            bits.append(f"{unpinned} unmeasurable (ranges, not versions)")
        if looking_up:
            bits.append(f"{looking_up} being looked up; push again when that finishes")
        if not_compared and not_compared > looking_up:
            bits.append(f"{not_compared - looking_up} could not be compared")
        print(f"{name}: {', '.join(bits)}")
        print(f"  {settings.server}{result['url']}")
        if result.get("lookups_refused"):
            print(
                "  warning: rate limit: PackageTrack's lookup queue is full for "
                f"this hour ({result['lookups_refused']} not looked up). "
                "Push again later.",
                file=sys.stderr,
            )
        similar = result.get("similar_to") or []
        if similar:
            best = similar[0]
            print(
                f"  note: project {best['name']!r} holds the same dependency "
                f"set ({best['overlap']:.0%} of the packages in common); to "
                f"update that one instead, push with --name {best['name']}",
                file=sys.stderr,
            )
        if similar[1:]:
            others = ", ".join(repr(s["name"]) for s in similar[1:])
            print(f"  note: also holding it: {others}", file=sys.stderr)

        for verdict in result.get("rules") or []:
            if verdict["met"]:
                continue
            mark = "FAIL" if verdict["action"] == "fail" else "warn"
            print(f"  {mark}: {verdict['message']}", file=sys.stderr)
            if verdict["action"] == "fail":
                broke_a_rule = True
        note = result.get("unmeasured_note")
        if note and not all(v["met"] for v in result.get("rules") or []):
            print(f"  {note}", file=sys.stderr)

    if broke_a_rule:
        print(
            "error: a rule your organization set was not met.",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    """Run `login`."""
    path = config.save(api_key=args.api_key, server=args.server)
    print(f"saved to {path}")
    return 0


MCP_MOVED = """\
packagetrackdev mcp is gone: the MCP server is its own package, packagetrackdev-mcp.
  install it:   curl -fsSL https://packagetrack.dev/install.sh | sh
                (installs both tools), or the server alone:
                uv tool install --find-links https://packagetrack.dev/cli/ packagetrackdev-mcp
  register it:  claude mcp add -s user packagetrackdev -- packagetrackdev-mcp
                (after: claude mcp remove packagetrackdev, if the old entry is there)
  https://github.com/packagetrack-dev/packagetrackdev-mcp"""  # noqa: E501


def cmd_mcp(args: argparse.Namespace) -> int:
    print(MCP_MOVED, file=sys.stderr)
    return 2


def installed_version() -> str:
    """Return the installed version, or "0.0.0" when not installed."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("packagetrackdev")
    except PackageNotFoundError:
        return "0.0.0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="packagetrackdev",
        description="What your build's dependencies changed since you locked them.",
    )
    parser.add_argument(
        "--version", action="version", version=f"packagetrackdev {installed_version()}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def shared(target: argparse.ArgumentParser) -> None:
        target.add_argument(
            "--project",
            type=Path,
            default=Path.cwd(),
            help="default: current directory",
        )
        target.add_argument(
            "--ecosystem",
            default=None,
            choices=lockfile_ecosystems(),
            help="default: every lock file found",
        )
        target.add_argument("--server", default=None)
        target.add_argument(
            "--dry-run",
            action="store_true",
            help="print exactly what would be sent, and send nothing",
        )

    check = sub.add_parser(
        "check", help="print what changed; nothing is stored and no account is used"
    )
    shared(check)
    check.add_argument("--all", action="store_true", help="also list unknown packages")
    check.set_defaults(func=cmd_check)

    push_cmd = sub.add_parser(
        "push", help="send this project's dependencies to your dashboard"
    )
    shared(push_cmd)
    push_cmd.add_argument("--name", default=None, help="default: the folder name")
    push_cmd.add_argument("--api-key", default=None, dest="api_key")
    push_cmd.set_defaults(func=cmd_push)

    login = sub.add_parser("login", help="store an API key on this machine")
    login.add_argument("--api-key", required=True, dest="api_key")
    login.add_argument("--server", default=None)
    login.set_defaults(func=cmd_login)

    mcp_cmd = sub.add_parser(
        "mcp",
        help="gone: the MCP server is the packagetrackdev-mcp package now",
    )
    mcp_cmd.add_argument("--api-key", default=None, dest="api_key")
    mcp_cmd.add_argument("--server", default=None)
    mcp_cmd.set_defaults(func=cmd_mcp)

    return parser


def _utf8_output() -> None:
    """Write stdout and stderr as UTF-8, whatever the platform's default is."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def main() -> int:
    _utf8_output()
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    sys.exit(main())
