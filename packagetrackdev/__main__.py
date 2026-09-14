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
from packagetrackdev.excerpt import summarise as _summarise
from packagetrackdev.lockfiles import (
    LOCKFILES,
    Dependency,
    Project,
    find,
    read,
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


def report(project: Project, data: dict, show_all: bool) -> None:
    """Print the report for one project."""
    by_name = {p["name"]: p for p in data.get("packages", [])}
    parents = {d.name: d.parents for d in project.dependencies}
    transitive = {d.name for d in project.dependencies if not d.direct}

    direct = [
        by_name[d.name]
        for d in project.direct
        if d.name in by_name and (by_name[d.name].get("versions_behind") or 0) > 0
    ]
    withdrawn = [p for p in data.get("packages", []) if p.get("installed_yanked")]
    unknown = [p for p in data.get("packages", []) if not p.get("known")]

    unpinned = [d for d in project.dependencies if not d.version]
    print(
        f"\n{project.source}: {data.get('checked', 0)} packages, "
        f"{len(project.direct)} of them yours.\n"
    )
    if project.note:
        print(f"{project.note}\n")
    if unpinned:
        one = len(unpinned) == 1
        print(
            f"{len(unpinned)} {'is a range' if one else 'are ranges'} rather than "
            f"{'a version' if one else 'versions'}, so how far behind "
            f"{'it is' if one else 'they are'} depends on when you last built."
        )
        for dep in unpinned[:8]:
            pkg = by_name.get(dep.name) or {}
            newest = pkg.get("latest_stable")
            print(f"  {dep.name}  newest release: {newest or 'unknown to us'}")
        if len(unpinned) > 8:
            print(f"  ...and {len(unpinned) - 8} more")
        print()

    if withdrawn:
        print("Withdrawn versions in this build:")
        for pkg in withdrawn:
            reason = (pkg.get("installed_yanked_reason") or "no reason given").strip()
            owners = parents.get(pkg["name"]) or []
            if owners:
                via = f"  (pulled in by {', '.join(owners[:3])})"
            elif pkg["name"] in transitive:
                via = "  (indirect, this file does not record what requires it)"
            else:
                via = "  (yours)"
            print(f"  {pkg['name']} {pkg['installed']}{via}")
            for line in _summarise(reason)[:2]:
                print(f"      {line}")
        print()

    if direct:
        print("Your dependencies, behind:")
        for pkg in sorted(direct, key=lambda p: -(p.get("versions_behind") or 0)):
            print(
                f"\n{pkg['name']} {pkg['installed']} -> {pkg.get('latest_stable')}"
                f"   {pkg['versions_behind']} behind"
            )
            for note in pkg.get("notes", [])[:NOTES_SHOWN]:
                print(f"  {note['version']}")
                for line in _summarise(note["body"]):
                    print(f"    {line}")
    else:
        print("Your own dependencies are all current.")

    behind_indirect = sum(
        1
        for p in data.get("packages", [])
        if (p.get("versions_behind") or 0) > 0 and p["name"] in transitive
    )
    if behind_indirect:
        print(
            f"\n{behind_indirect} packages you did not ask for are also behind. "
            "They come with the ones above and follow when those are updated."
        )

    if show_all and unknown:
        print("\nNot in the archive (we track the most-depended-on per registry):")
        print("  " + ", ".join(p["name"] for p in unknown[:40]))


def ask(server: str, ecosystem: str, packages: list[Dependency]) -> dict:
    """Query the server in chunks and merge the responses."""
    url = f"{server.rstrip('/')}/api/status"
    merged: dict = {"ecosystem": ecosystem, "checked": 0, "behind": 0, "packages": []}

    with httpx.Client(timeout=REQUEST_TIMEOUT, headers=_user_agent()) as client:
        for start in range(0, len(packages), CHUNK):
            batch = packages[start : start + CHUNK]
            response = client.post(url, json=payload(ecosystem, batch))
            response.raise_for_status()
            part = response.json()
            merged["checked"] += part.get("checked", 0)
            merged["behind"] += part.get("behind", 0)
            merged["packages"].extend(part.get("packages", []))

    return merged


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
        try:
            data = ask(settings.server, project.ecosystem, project.dependencies)
        except httpx.HTTPError as exc:
            print(f"error: {http_failure(exc, settings.server)}", file=sys.stderr)
            return 2
        report(project, data, show_all=args.all)
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

        bits = [f"{result['stored']} packages from {project.source}"]
        if result["withdrawn"]:
            bits.append(f"{result['withdrawn']} withdrawn")
        bits.append(f"{result['behind']} of yours behind")
        if result.get("unpinned"):
            bits.append(f"{result['unpinned']} unmeasurable (ranges, not versions)")
        print(f"{name}: {', '.join(bits)}")
        print(f"  {settings.server}{result['url']}")

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
                uv tool install "packagetrackdev-mcp @ https://packagetrack.dev/cli/packagetrackdev-mcp-latest.whl"
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
            choices=("pypi", "npm"),
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


def main() -> int:
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
