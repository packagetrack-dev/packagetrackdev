"""Lock file and manifest parsers."""

from __future__ import annotations

import json
import logging
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from packagetrackdev import sbom

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Dependency:
    name: str
    version: str
    parents: list[str] = field(default_factory=list)
    indirect: bool = False

    @property
    def direct(self) -> bool:
        return not self.parents and not self.indirect


@dataclass(slots=True)
class Project:
    ecosystem: str
    source: str
    dependencies: list[Dependency]
    skipped: int = 0
    note: str | None = None

    @property
    def direct(self) -> list[Dependency]:
        return [d for d in self.dependencies if d.direct]


LOCKFILES = (
    ("npm", "package-lock.json"),
    ("npm", "npm-shrinkwrap.json"),
    ("pypi", "uv.lock"),
    ("pypi", "poetry.lock"),
    ("cargo", "Cargo.lock"),
    ("composer", "composer.lock"),
    ("go", "go.mod"),
)

MANIFESTS = (
    ("npm", "package.json"),
    ("pypi", "requirements.txt"),
)


def find(project: Path) -> list[tuple[str, Path]]:
    """Find the dependency file for each ecosystem, preferring lock files."""
    chosen: dict[str, Path] = {}
    for ecosystem, name in (*LOCKFILES, *MANIFESTS):
        path = project / name
        if ecosystem not in chosen and path.is_file():
            chosen[ecosystem] = path
    return [(ecosystem, path) for ecosystem, path in chosen.items()]


DECLARATIONS = frozenset(name for _, name in MANIFESTS)

SUPPORTED_FILES = tuple(name for _, name in (*LOCKFILES, *MANIFESTS))

_REQUIREMENT_LINE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*\s*(\[[^\]]*\])?\s*"
    r"((==|===|!=|<=?|>=?|~=)\s*[^\s;,]+(\s*,\s*(==|===|!=|<=?|>=?|~=)\s*[^\s;,]+)*)?"
    r"\s*(;.*)?$"
)


def detect(content: str, filename: str | None = None) -> tuple[str, str] | None:
    """Detect the file type of `content`, as (ecosystem, canonical name)."""
    if filename:
        base = filename.replace("\\", "/").rsplit("/", 1)[-1]
        for ecosystem, name in (*LOCKFILES, *MANIFESTS):
            if base.lower() == name.lower():
                return ecosystem, name

    try:
        data = json.loads(content)
    except ValueError:
        data = None
    if data is not None:
        if not isinstance(data, dict):
            return None
        which = sbom.looks_like(data)
        if which is not None:
            reading = sbom.read(content)
            groups = reading.by_ecosystem() if reading else {}
            if len(groups) != 1:
                return None
            return next(iter(groups)), which
        if isinstance(data.get("packages"), dict) or "lockfileVersion" in data:
            return "npm", "package-lock.json"
        if isinstance(data.get("packages"), list) or isinstance(
            data.get("packages-dev"), list
        ):
            return "composer", "composer.lock"
        if isinstance(data.get("dependencies"), dict) or isinstance(
            data.get("devDependencies"), dict
        ):
            return "npm", "package.json"
        return None

    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        data = None
    if isinstance(data, dict) and isinstance(data.get("package"), list):
        if "requires-python" in data:
            return "pypi", "uv.lock"
        metadata = data.get("metadata")
        if isinstance(metadata, dict) and "content-hash" in metadata:
            return "pypi", "poetry.lock"
        entries = [e for e in data["package"] if isinstance(e, dict)]
        if any(isinstance(e.get("source"), dict) for e in entries):
            return "pypi", "uv.lock"
        if any(isinstance(e.get("source"), str) or "checksum" in e for e in entries):
            return "cargo", "Cargo.lock"
        return None

    if _looks_like_gomod(content):
        return "go", "go.mod"

    lines = [
        stripped
        for raw in content.splitlines()
        if (stripped := raw.split("#", 1)[0].strip())
    ]
    candidates = [line for line in lines if not line.startswith("-")]
    if candidates and all(_REQUIREMENT_LINE.match(line) for line in candidates):
        return "pypi", "requirements.txt"
    return None


def read(ecosystem: str, path: Path) -> Project | None:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("could not read %s: %s", path, exc)
        return None
    return parse(ecosystem, path.name, content)


def _read_sbom(ecosystem: str, filename: str, content: str) -> Project | None:
    """Read one ecosystem's components from an SBOM."""
    reading = sbom.read(content)
    if reading is None:
        return None
    mine = reading.by_ecosystem().get(ecosystem, [])
    dependencies = [
        Dependency(
            name=component.name,
            version=component.version,
            parents=list(component.parents),
            indirect=not component.direct and not component.parents,
        )
        for component in mine
    ]
    return Project(
        ecosystem=ecosystem,
        source=filename,
        dependencies=dependencies,
        skipped=reading.skipped,
        note=sbom.caveat(reading),
    )


def parse(ecosystem: str, filename: str, content: str) -> Project | None:
    """Parse lock or manifest content by canonical file name."""
    try:
        if filename in sbom.FORMATS:
            return _read_sbom(ecosystem, filename, content)
        if filename == "go.mod":
            return _read_gomod(ecosystem, filename, content)
        if filename == "package.json":
            return _read_package_json(ecosystem, filename, content)
        if filename == "requirements.txt":
            return _read_requirements(ecosystem, filename, content)
        if filename == "composer.lock":
            return _read_composer(ecosystem, filename, content)
        if filename == "Cargo.lock":
            return _read_cargo(ecosystem, filename, content)
        if filename.endswith(".json"):
            return _read_npm(ecosystem, filename, content)
        return _read_toml(ecosystem, filename, content)
    except (ValueError, tomllib.TOMLDecodeError) as exc:
        log.warning("could not parse %s: %s", filename, exc)
        return None


def _read_npm(ecosystem: str, source: str, content: str) -> Project | None:
    """Parse `package-lock.json` (v2 and v3)."""
    data = json.loads(content)
    entries = data.get("packages")
    if not isinstance(entries, dict):
        return None

    real_name: dict[str, str] = {}
    for location, meta in entries.items():
        if not location or "node_modules/" not in location:
            continue
        if not isinstance(meta, dict):
            continue
        folder = location.split("node_modules/")[-1]
        published = meta.get("name")
        if isinstance(published, str) and published and published != folder:
            real_name[folder] = published

    def resolve(spelling: str) -> str:
        return real_name.get(spelling, spelling)

    root = entries.get("", {})
    declared = {
        resolve(name)
        for name in (*root.get("dependencies", {}), *root.get("devDependencies", {}))
    }

    installed: dict[str, str] = {}
    parents: dict[str, set[str]] = {}
    skipped = 0

    for location, meta in entries.items():
        if not location:
            continue
        name = resolve(location.split("node_modules/")[-1])
        version = meta.get("version") if isinstance(meta, dict) else None
        if not isinstance(version, str):
            skipped += 1
            continue
        installed.setdefault(f"{name}@{version}", version)
        for dependency in (
            *meta.get("dependencies", {}),
            *meta.get("peerDependencies", {}),
            *meta.get("optionalDependencies", {}),
        ):
            parents.setdefault(resolve(dependency), set()).add(name)

    out: list[Dependency] = []
    for key, version in installed.items():
        name = key.rsplit("@", 1)[0]
        owners = [] if name in declared else sorted(parents.get(name, ()))
        out.append(Dependency(name=name, version=version, parents=owners))

    return Project(
        ecosystem=ecosystem, source=source, dependencies=out, skipped=skipped
    )


def _read_cargo(ecosystem: str, source: str, content: str) -> Project | None:
    """Parse `Cargo.lock`."""
    data = tomllib.loads(content)
    packages = data.get("package")
    if not isinstance(packages, list):
        return None

    local: set[str] = set()
    versions: dict[str, str] = {}
    parents: dict[str, set[str]] = {}
    skipped = 0

    for entry in packages:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            skipped += 1
            continue
        name, version = entry["name"], entry.get("version")

        if not entry.get("source"):
            local.add(name)
        elif isinstance(version, str):
            versions[name] = version

        for dep in entry.get("dependencies") or []:
            if isinstance(dep, str):
                parents.setdefault(dep.split(" ", 1)[0], set()).add(name)

    return Project(
        ecosystem=ecosystem,
        source=source,
        dependencies=[
            Dependency(
                name=name,
                version=version,
                parents=sorted(parents.get(name, set()) - local),
            )
            for name, version in sorted(versions.items())
        ],
        skipped=skipped,
    )


def _read_composer(ecosystem: str, source: str, content: str) -> Project | None:
    """Parse `composer.lock`."""
    data = json.loads(content)
    blocks = data.get("packages"), data.get("packages-dev")
    if not any(isinstance(b, list) for b in blocks):
        return None

    versions: dict[str, str] = {}
    requires: dict[str, set[str]] = {}
    for block in blocks:
        if not isinstance(block, list):
            continue
        for entry in block:
            if not isinstance(entry, dict):
                continue
            name, version = entry.get("name"), entry.get("version")
            if not _is_composer_package(name) or not isinstance(version, str):
                continue
            versions[name] = version
            for dep in entry.get("require") or {}:
                if _is_composer_package(dep):
                    requires.setdefault(dep, set()).add(name)

    return Project(
        ecosystem=ecosystem,
        source=source,
        dependencies=[
            Dependency(
                name=name,
                version=version,
                parents=sorted(requires.get(name, ())),
            )
            for name, version in sorted(versions.items())
        ],
    )


def _is_composer_package(name: object) -> bool:
    """Return True for a `vendor/package` name, False for platform requirements."""
    return isinstance(name, str) and "/" in name and not name.startswith("ext-")


def _read_toml(ecosystem: str, source: str, content: str) -> Project | None:
    """Parse `uv.lock` or `poetry.lock`."""
    data = tomllib.loads(content)
    packages = data.get("package")
    if not isinstance(packages, list):
        return None

    declared: set[str] = set()
    parents: dict[str, set[str]] = {}
    versions: dict[str, str] = {}
    skipped = 0

    for entry in packages:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            skipped += 1
            continue
        name, version = entry["name"], entry.get("version")

        origin = entry.get("source") or {}
        is_root = isinstance(origin, dict) and (
            "virtual" in origin or "editable" in origin
        )
        needs = _toml_dependencies(entry)

        if is_root:
            declared |= needs
            continue

        if isinstance(version, str):
            versions[name] = version
        for dependency in needs:
            parents.setdefault(dependency, set()).add(name)

    return Project(
        ecosystem=ecosystem,
        source=source,
        dependencies=[
            Dependency(
                name=name,
                version=version,
                parents=[] if name in declared else sorted(parents.get(name, ())),
            )
            for name, version in sorted(versions.items())
        ],
        skipped=skipped,
    )


def _toml_dependencies(entry: dict) -> set[str]:
    """Return the dependency names of one lock entry."""
    names: set[str] = set()

    for item in entry.get("dependencies") or []:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            names.add(item["name"])
        elif isinstance(item, str):
            names.add(item)

    metadata = entry.get("metadata") or {}
    for item in (
        (metadata.get("requires-dist") or []) if isinstance(metadata, dict) else []
    ):
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            names.add(item["name"])

    poetry = entry.get("dependencies")
    if isinstance(poetry, dict):
        names |= {k for k in poetry if isinstance(k, str)}

    return names


_REQUIREMENT = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*(?P<extras>\[[^\]]*\])?\s*"
    r"(?P<op>==|===)\s*(?P<version>[^\s;#]+)"
)
_REQUIREMENT_NAME = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)")


def _read_requirements(ecosystem: str, source: str, content: str) -> Project | None:
    """Parse `requirements.txt`."""
    dependencies: list[Dependency] = []
    skipped = 0
    for raw in content.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-"):
            skipped += 1
            continue

        pinned = _REQUIREMENT.match(line)
        if pinned:
            dependencies.append(
                Dependency(name=pinned["name"], version=pinned["version"])
            )
            continue

        loose = _REQUIREMENT_NAME.match(line)
        if loose:
            dependencies.append(Dependency(name=loose["name"], version=""))
        else:
            skipped += 1

    return Project(
        ecosystem=ecosystem,
        source=source,
        dependencies=dependencies,
        skipped=skipped,
    )


def _read_package_json(ecosystem: str, source: str, content: str) -> Project | None:
    """Parse `package.json`."""
    data = json.loads(content)
    declared = {
        **(data.get("dependencies") or {}),
        **(data.get("devDependencies") or {}),
    }
    return Project(
        ecosystem=ecosystem,
        source=source,
        dependencies=[
            Dependency(name=name, version="")
            for name in sorted(declared)
            if isinstance(name, str)
        ],
    )


_GO_DIRECTIVES = frozenset(
    {
        "module",
        "go",
        "toolchain",
        "godebug",
        "require",
        "exclude",
        "replace",
        "retract",
        "tool",
    }
)

_GO_VERSION = re.compile(r"^v\d")

_GO_MODULE_LINE = re.compile(r"^module\s+\S+$")
_GO_OTHER_DIRECTIVE = re.compile(r"^(go|toolchain|require|replace|exclude)\b")

MAX_NAME_CHARS = 255
MAX_VERSION_CHARS = 256


def _looks_like_gomod(content: str) -> bool:
    """Return True if `content` looks like a `go.mod` file."""
    lines = [
        stripped
        for raw in content.splitlines()
        if (stripped := raw.split("//", 1)[0].strip())
    ]
    return any(_GO_MODULE_LINE.match(line) for line in lines) and any(
        _GO_OTHER_DIRECTIVE.match(line) for line in lines
    )


def _go_tokens(line: str) -> list[str]:
    """Tokenise one `go.mod` line."""
    spaced = line.replace("(", " ( ").replace(")", " ) ")
    return [token.strip('"`') for token in spaced.split()]


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _read_gomod(ecosystem: str, source: str, content: str) -> Project | None:
    """Parse `go.mod`."""
    module_path: str | None = None
    go_directive: str | None = None
    requires: dict[str, tuple[str, bool]] = {}
    replaced: set[str] = set()
    skipped = 0
    block: str | None = None

    for raw in content.splitlines():
        body, _, comment = raw.partition("//")
        if not body.strip():
            continue

        if block is not None:
            tokens = _go_tokens(body)
            if tokens[0] == ")":
                block = None
                continue
            keyword, args = block, tokens
        else:
            tokens = _go_tokens(body)
            keyword, args = tokens[0], tokens[1:]
            if keyword not in _GO_DIRECTIVES:
                skipped += 1
                log.warning(
                    "go.mod: unknown directive, line skipped: %r", raw.strip()[:120]
                )
                continue
            if args and args[0] == "(":
                block = keyword
                if len(args) > 1:
                    skipped += 1
                    log.warning(
                        "go.mod: content on the line opening a %s block, not read: %r",
                        keyword,
                        raw.strip()[:120],
                    )
                continue

        if keyword == "module":
            if args:
                module_path = args[0]
        elif keyword == "go":
            go_directive = args[0] if args else None
        elif keyword in {"toolchain", "godebug", "tool", "exclude", "retract"}:
            continue
        elif keyword == "require":
            name, version = (args + ["", ""])[:2]
            if not name or not _GO_VERSION.match(version):
                skipped += 1
                log.warning(
                    "go.mod: require line without a module and version, skipped: %r",
                    raw.strip()[:120],
                )
                continue
            if len(name) > MAX_NAME_CHARS or len(version) > MAX_VERSION_CHARS:
                skipped += 1
                log.warning(
                    "go.mod: %s@%s exceeds the %s/%s character limit, skipped",
                    name[:80],
                    version[:40],
                    MAX_NAME_CHARS,
                    MAX_VERSION_CHARS,
                )
                continue
            requires[name] = (version, "indirect" in comment.split())
        elif keyword == "replace":
            if args:
                replaced.add(args[0])
                log.info(
                    "go.mod: %s is replaced, so it is not reported: %r",
                    args[0],
                    raw.strip()[:120],
                )

    if module_path:
        requires.pop(module_path, None)

    dropped = sorted(replaced & set(requires))
    for name in dropped:
        del requires[name]
    if dropped:
        skipped += len(dropped)
        log.warning(
            "go.mod: %s replaced %s not reported: %s",
            len(dropped),
            "module" if len(dropped) == 1 else "modules",
            ", ".join(dropped),
        )

    return Project(
        ecosystem=ecosystem,
        source=source,
        dependencies=[
            Dependency(name=name, version=version, indirect=indirect)
            for name, (version, indirect) in sorted(requires.items())
        ],
        skipped=skipped,
        note=_gomod_note(go_directive, dropped),
    )


def _gomod_note(go_directive: str | None, dropped: list[str]) -> str:
    """Return the caveat for a `go.mod` read, if any."""
    parts = [
        "go.mod marks which modules are indirect but never records which "
        "module required them, so indirect rows here name no parent."
    ]
    if _go_before_117(go_directive):
        parts.append(
            f"This file targets Go {go_directive}, which lists only some "
            "indirect modules, so the indirect set here may be incomplete."
        )
    if dropped:
        parts.append(
            f"{_plural(len(dropped), 'module is', 'modules are')} replaced by a "
            "replace directive and left out: the build uses other code under "
            "that name, so the published version is not what runs."
        )
    return " ".join(parts)


def _go_before_117(go_directive: str | None) -> bool:
    """Return True for Go versions before 1.17."""
    if not go_directive:
        return False
    parts = go_directive.split(".")
    try:
        return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0) < (1, 17)
    except ValueError:
        return False
