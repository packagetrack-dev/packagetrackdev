"""Reading a CycloneDX or SPDX bill of materials."""

import json

import pytest
from packagetrackdev import lockfiles, sbom

CYCLONE = {
    "bomFormat": "CycloneDX",
    "specVersion": "1.5",
    "metadata": {
        "component": {"bom-ref": "root", "name": "app", "type": "application"}
    },
    "components": [
        {
            "bom-ref": "a",
            "type": "library",
            "name": "flask",
            "version": "3.0.0",
            "purl": "pkg:pypi/flask@3.0.0",
        },
        {
            "bom-ref": "b",
            "type": "library",
            "name": "werkzeug",
            "version": "3.0.1",
            "purl": "pkg:pypi/werkzeug@3.0.1",
        },
    ],
    "dependencies": [
        {"ref": "root", "dependsOn": ["a"]},
        {"ref": "a", "dependsOn": ["b"]},
    ],
}

SPDX_DOC = {
    "spdxVersion": "SPDX-2.3",
    "SPDXID": "SPDXRef-DOCUMENT",
    "packages": [
        {
            "SPDXID": "SPDXRef-app",
            "name": "app",
        },
        {
            "SPDXID": "SPDXRef-flask",
            "name": "flask",
            "versionInfo": "3.0.0",
            "externalRefs": [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": "pkg:pypi/flask@3.0.0",
                }
            ],
        },
        {
            "SPDXID": "SPDXRef-werkzeug",
            "name": "werkzeug",
            "versionInfo": "3.0.1",
            "externalRefs": [
                {"referenceType": "purl", "referenceLocator": "pkg:pypi/werkzeug@3.0.1"}
            ],
        },
    ],
    "relationships": [
        {
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": "SPDXRef-app",
        },
        {
            "spdxElementId": "SPDXRef-app",
            "relationshipType": "DEPENDS_ON",
            "relatedSpdxElement": "SPDXRef-flask",
        },
        {
            "spdxElementId": "SPDXRef-flask",
            "relationshipType": "DEPENDS_ON",
            "relatedSpdxElement": "SPDXRef-werkzeug",
        },
    ],
}


def text(document) -> str:
    return json.dumps(document)


@pytest.mark.parametrize(
    "purl,expected",
    [
        ("pkg:pypi/flask@3.0.0", ("pypi", "flask", "3.0.0")),
        ("pkg:npm/%40types/node@22.0.0", ("npm", "@types/node", "22.0.0")),
        ("pkg:cargo/serde@1.0.0?arch=x86", ("cargo", "serde", "1.0.0")),
        ("pkg:golang/github.com/x/y@v1.2.3", ("golang", "github.com/x/y", "v1.2.3")),
        ("pkg:PyPI/Flask@3.0.0", ("pypi", "Flask", "3.0.0")),
    ],
)
def test_parse_purl(purl, expected):
    assert sbom.parse_purl(purl) == expected


def test_parse_purl_scoped_npm():
    assert sbom.parse_purl("pkg:npm/%40types/node@1.0.0")[1] == "@types/node"


@pytest.mark.parametrize(
    "purl",
    ["", "flask@3.0.0", "pkg:pypi/flask", "pkg:pypi@3.0.0", "pkg:/flask@3.0.0"],
)
def test_parse_purl_invalid(purl):
    assert sbom.parse_purl(purl) is None


def test_looks_like_formats():
    assert sbom.looks_like(CYCLONE) == sbom.CYCLONEDX
    assert sbom.looks_like(SPDX_DOC) == sbom.SPDX


def test_looks_like_lock_file():
    assert sbom.looks_like({"lockfileVersion": 3, "packages": {}}) is None
    assert sbom.looks_like({"packages": [], "packages-dev": []}) is None


def test_spdx_not_composer():
    assert lockfiles.detect(text(SPDX_DOC)) == ("pypi", sbom.SPDX)


def test_cyclonedx_components():
    reading = sbom.read(text(CYCLONE))
    assert reading.format == sbom.CYCLONEDX
    assert [(c.name, c.version) for c in reading.components] == [
        ("flask", "3.0.0"),
        ("werkzeug", "3.0.1"),
    ]


def test_cyclonedx_direct():
    reading = sbom.read(text(CYCLONE))
    flask, werkzeug = reading.components
    assert flask.direct
    assert not werkzeug.direct
    assert werkzeug.parents == ["flask"]


def test_spdx_components():
    reading = sbom.read(text(SPDX_DOC))
    assert reading.format == sbom.SPDX
    flask, werkzeug = reading.components
    assert flask.direct and not werkzeug.direct
    assert werkzeug.parents == ["flask"]
    assert reading.skipped == 1


def test_component_without_purl():
    document = json.loads(text(CYCLONE))
    document["components"].append({"type": "operating-system", "name": "alpine"})
    reading = sbom.read(json.dumps(document))
    assert reading.skipped == 1
    assert len(reading.components) == 2


def test_nested_components():
    document = json.loads(text(CYCLONE))
    document["components"][0]["components"] = [
        {"name": "click", "version": "8.1.0", "purl": "pkg:pypi/click@8.1.0"}
    ]
    reading = sbom.read(json.dumps(document))
    assert "click" in [c.name for c in reading.components]


def test_caveat_without_graph():
    document = json.loads(text(CYCLONE))
    del document["dependencies"]
    reading = sbom.read(json.dumps(document))
    assert reading.graph_missing
    assert all(c.direct for c in reading.components)
    note = sbom.caveat(reading)
    assert note and "no dependency graph" in note


def test_caveat_with_graph():
    assert sbom.caveat(sbom.read(text(CYCLONE))) is None


def test_read_not_sbom():
    assert sbom.read("not json") is None
    assert sbom.read('{"lockfileVersion": 3}') is None


def mixed() -> str:
    document = json.loads(text(CYCLONE))
    document["components"].append(
        {
            "bom-ref": "c",
            "name": "left-pad",
            "version": "1.3.0",
            "purl": "pkg:npm/left-pad@1.3.0",
        }
    )
    return json.dumps(document)


def test_mixed_ecosystems_grouped():
    groups = sbom.read(mixed()).by_ecosystem()
    assert sorted(groups) == ["npm", "pypi"]
    assert len(groups["pypi"]) == 2


def test_mixed_ecosystems_projects():
    assert lockfiles.detect(mixed()) is None


def test_detect_format_name():
    assert lockfiles.detect(text(CYCLONE)) == ("pypi", sbom.CYCLONEDX)


def test_parse_dependency_shape():
    project = lockfiles.parse("pypi", sbom.CYCLONEDX, text(CYCLONE))
    assert project.ecosystem == "pypi"
    assert project.source == sbom.CYCLONEDX
    assert [d.name for d in project.direct] == ["flask"]
    werkzeug = next(d for d in project.dependencies if d.name == "werkzeug")
    assert werkzeug.parents == ["flask"]


def test_parse_ecosystem_filter():
    project = lockfiles.parse("npm", sbom.CYCLONEDX, mixed())
    assert [d.name for d in project.dependencies] == ["left-pad"]


def test_caveat_in_project():
    document = json.loads(text(CYCLONE))
    del document["dependencies"]
    project = lockfiles.parse("pypi", sbom.CYCLONEDX, json.dumps(document))
    assert project.note and "no dependency graph" in project.note


def test_skipped_count_in_project():
    document = json.loads(text(CYCLONE))
    document["components"].append({"type": "file", "name": "README"})
    project = lockfiles.parse("pypi", sbom.CYCLONEDX, json.dumps(document))
    assert project.skipped == 1
