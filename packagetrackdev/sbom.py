"""CycloneDX and SPDX SBOM parsers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from urllib.parse import unquote

CYCLONEDX = "CycloneDX"
SPDX = "SPDX"

FORMATS = (CYCLONEDX, SPDX)


@dataclass(slots=True)
class Component:
    """One component of an SBOM."""

    purl_type: str
    name: str
    version: str
    direct: bool = True
    parents: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Reading:
    """The result of reading one SBOM."""

    format: str
    components: list[Component]
    skipped: int
    graph_missing: bool = False

    def by_ecosystem(self) -> dict[str, list[Component]]:
        groups: dict[str, list[Component]] = {}
        for component in self.components:
            groups.setdefault(component.purl_type, []).append(component)
        return groups


def parse_purl(purl: str) -> tuple[str, str, str] | None:
    """Parse a purl into (ecosystem, name, version)."""
    if not purl.startswith("pkg:"):
        return None
    body = purl[4:].split("#", 1)[0].split("?", 1)[0]
    if "/" not in body:
        return None
    purl_type, _, rest = body.partition("/")
    name, _, version = rest.partition("@")
    if not purl_type or not name or not version:
        return None
    return purl_type.lower(), unquote(name), unquote(version)


def looks_like(data: object) -> str | None:
    """Return the SBOM format of parsed JSON, or None."""
    if not isinstance(data, dict):
        return None
    if data.get("bomFormat") == CYCLONEDX:
        return CYCLONEDX
    if "specVersion" in data and "components" in data:
        return CYCLONEDX
    if "spdxVersion" in data or data.get("SPDXID") == "SPDXRef-DOCUMENT":
        return SPDX
    return None


def _cyclonedx(data: dict) -> Reading:
    components: list[Component] = []
    skipped = 0
    by_ref: dict[str, Component] = {}

    def walk(items: list) -> None:
        nonlocal skipped
        for item in items:
            if not isinstance(item, dict):
                skipped += 1
                continue
            parsed = parse_purl(str(item.get("purl") or ""))
            if parsed is None:
                skipped += 1
            else:
                purl_type, name, version = parsed
                component = Component(purl_type, name, version)
                components.append(component)
                ref = item.get("bom-ref") or item.get("purl")
                if isinstance(ref, str):
                    by_ref[ref] = component
            nested = item.get("components")
            if isinstance(nested, list):
                walk(nested)

    walk(data.get("components") if isinstance(data.get("components"), list) else [])

    graph = data.get("dependencies")
    if not isinstance(graph, list) or not graph:
        return Reading(CYCLONEDX, components, skipped, graph_missing=True)

    root = None
    metadata = data.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("component"), dict):
        root = metadata["component"].get("bom-ref")

    depends: dict[str, list[str]] = {}
    for entry in graph:
        if isinstance(entry, dict) and isinstance(entry.get("ref"), str):
            children = entry.get("dependsOn")
            depends[entry["ref"]] = [c for c in children or [] if isinstance(c, str)]

    _apply_graph(by_ref, depends, root)
    return Reading(CYCLONEDX, components, skipped)


def _spdx(data: dict) -> Reading:
    components: list[Component] = []
    skipped = 0
    by_ref: dict[str, Component] = {}

    for item in data.get("packages") or []:
        if not isinstance(item, dict):
            skipped += 1
            continue
        purl = None
        for ref in item.get("externalRefs") or []:
            if isinstance(ref, dict) and ref.get("referenceType") == "purl":
                purl = str(ref.get("referenceLocator") or "")
                break
        parsed = parse_purl(purl or "")
        if parsed is None:
            skipped += 1
            continue
        purl_type, name, version = parsed
        component = Component(purl_type, name, version)
        components.append(component)
        spdx_id = item.get("SPDXID")
        if isinstance(spdx_id, str):
            by_ref[spdx_id] = component

    relationships = data.get("relationships")
    if not isinstance(relationships, list) or not relationships:
        return Reading(SPDX, components, skipped, graph_missing=True)

    root = None
    depends: dict[str, list[str]] = {}
    for entry in relationships:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("relationshipType")
        source = entry.get("spdxElementId")
        target = entry.get("relatedSpdxElement")
        if not isinstance(source, str) or not isinstance(target, str):
            continue
        if kind == "DESCRIBES" and source == "SPDXRef-DOCUMENT":
            root = target
        elif kind == "DEPENDS_ON":
            depends.setdefault(source, []).append(target)

    _apply_graph(by_ref, depends, root)
    return Reading(SPDX, components, skipped)


def _apply_graph(
    by_ref: dict[str, Component], depends: dict[str, list[str]], root: str | None
) -> None:
    """Mark direct dependencies and record parents from the dependency graph."""
    for parent_ref, children in depends.items():
        parent = by_ref.get(parent_ref)
        for child_ref in children:
            child = by_ref.get(child_ref)
            if child is None or parent is None or parent is child:
                continue
            if parent.name not in child.parents:
                child.parents.append(parent.name)

    if root is None:
        return
    direct = set(depends.get(root) or [])
    for ref, component in by_ref.items():
        component.direct = ref in direct


def read(content: str) -> Reading | None:
    """Read an SBOM, or return None if the content is not one."""
    try:
        data = json.loads(content)
    except ValueError:
        return None
    which = looks_like(data)
    if which == CYCLONEDX:
        return _cyclonedx(data)
    if which == SPDX:
        return _spdx(data)
    return None


def caveat(reading: Reading) -> str | None:
    """Return a caveat about this reading, or None."""
    if reading.graph_missing:
        return (
            "This SBOM carries no dependency graph, so every package is "
            "reported as a direct dependency."
        )
    return None
