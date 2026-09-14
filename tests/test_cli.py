"""The customer-facing command."""

import json
import logging
from pathlib import Path

import pytest
from packagetrackdev.__main__ import _summarise, payload
from packagetrackdev.lockfiles import Dependency, find, read


def test_payload_names_and_versions_only():
    body = payload("pypi", [Dependency("requests", "2.28.0")])
    assert body == {
        "ecosystem": "pypi",
        "packages": [{"name": "requests", "version": "2.28.0"}],
    }


def test_no_lock_file(tmp_path: Path):
    assert find(tmp_path) == []


def test_npm_lock_parents(tmp_path: Path):
    (tmp_path / "package-lock.json").write_text(
        json.dumps(
            {
                "packages": {
                    "": {"dependencies": {"express": "^5.0.0"}},
                    "node_modules/express": {
                        "version": "5.2.1",
                        "dependencies": {"glob": "^7.0.0"},
                    },
                    "node_modules/glob": {
                        "version": "7.2.3",
                        "dependencies": {"inflight": "^1.0.0"},
                    },
                    "node_modules/inflight": {"version": "1.0.6"},
                }
            }
        )
    )
    project = read("npm", tmp_path / "package-lock.json")
    by_name = {d.name: d for d in project.dependencies}

    assert by_name["express"].direct, "declared in the manifest, so it is yours"
    assert by_name["inflight"].parents == ["glob"]
    assert by_name["glob"].parents == ["express"]


def test_npm_lock_aliased_folder(tmp_path: Path):
    (tmp_path / "package-lock.json").write_text(
        json.dumps(
            {
                "packages": {
                    "": {"dependencies": {"wrap-ansi-cjs": "npm:wrap-ansi@^7.0.0"}},
                    "node_modules/wrap-ansi-cjs": {
                        "name": "wrap-ansi",
                        "version": "7.0.0",
                        "dependencies": {"string-width-cjs": "npm:string-width@^4.2.0"},
                    },
                    "node_modules/string-width-cjs": {
                        "name": "string-width",
                        "version": "4.2.3",
                    },
                }
            }
        )
    )
    project = read("npm", tmp_path / "package-lock.json")
    by_name = {d.name: d for d in project.dependencies}

    assert set(by_name) == {"wrap-ansi", "string-width"}
    assert by_name["string-width"].version == "4.2.3"
    assert by_name["wrap-ansi"].direct
    assert by_name["string-width"].parents == ["wrap-ansi"]


def test_npm_lock_workspace_folder(tmp_path: Path):
    (tmp_path / "package-lock.json").write_text(
        json.dumps(
            {
                "packages": {
                    "": {"dependencies": {"express": "^5.0.0"}},
                    "packages/ui": {"name": "@myapp/ui", "version": "1.0.0"},
                    "node_modules/express": {"version": "5.2.1"},
                }
            }
        )
    )
    project = read("npm", tmp_path / "package-lock.json")
    assert "express" in {d.name for d in project.dependencies}
    assert "@myapp/ui" not in {d.name for d in project.dependencies}


def test_npm_lock_nested_copies(tmp_path: Path):
    (tmp_path / "package-lock.json").write_text(
        json.dumps(
            {
                "packages": {
                    "": {},
                    "node_modules/glob": {"version": "13.0.6"},
                    "node_modules/rimraf/node_modules/glob": {"version": "7.2.3"},
                }
            }
        )
    )
    project = read("npm", tmp_path / "package-lock.json")
    assert sorted(d.version for d in project.dependencies if d.name == "glob") == [
        "13.0.6",
        "7.2.3",
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "* Add `max_body_size` by @Kludex in https://github.com/x/y/pull/1",
            "Add max_body_size",
        ),
        ("- Fixed [#190](https://x/190) properly", "Fixed #190 properly"),
        (r"\[`pylint`\] Fix false negatives", "[pylint] Fix false negatives"),
    ],
)
def test_summarise_prose(raw, expected):
    assert _summarise(raw) == [expected]


def test_summarise_drops_bookkeeping():
    body = "## What's Changed\n\nAdded a thing\n\n**Full Changelog**: https://x/y"
    assert _summarise(body) == ["Added a thing"]


def test_clip_at_word_boundary():
    body = "word " * 60
    line = _summarise(body)[0]
    assert line.endswith("…")
    assert len(line) <= 93
    assert not line.rstrip("…").endswith("wor")


def test_summarise_skips_headings():
    body = "# Heading\n\n\n## Another\n\nThe actual change\n"
    assert _summarise(body) == ["Heading", "Another", "The actual change"]


def test_summarise_scaffolding_sqlalchemy():
    body = (
        "2.0.52\n\n"
        "Released: August 11, 2026\n\n"
        "platform\n\n"
        "[platform] [bug] Python 3.15 support has been added\n"
    )
    assert _summarise(body) == ["[platform] [bug] Python 3.15 support has been added"]


def test_summarise_keeps_section_heading():
    body = "Features\n\nRequire Python 3.10 or later.\n"
    assert _summarise(body) == ["Features", "Require Python 3.10 or later."]


@pytest.mark.parametrize(
    "debris",
    [
        "2.0.52",
        "v3.1.0",
        "2026-08-11",
        "August 11, 2026",
        "Released: today",
        "[15.0.0] - 2026-04-12",
        "Changed",
        "Fixed",
        "### Security",
    ],
)
def test_summarise_version_date_lines(debris):
    assert _summarise(f"{debris}\nFixed a crash on empty input\n") == [
        "Fixed a crash on empty input"
    ]


def test_summarise_html_seleniumbase():
    body = (
        '&gt; This resolves <a class="issue-link js-issue-link" '
        'data-error-text="Failed to load…\n'
        "&gt; (Due to this bug, the MCP Server only worked on Python 3.14+)<br>\n"
        "&gt; (Caused by a missing line: <code>from __future__ import "
        "annotations</code>)</li>\n"
    )
    lines = _summarise(body)
    assert lines == [
        "This resolves",
        "(Due to this bug, the MCP Server only worked on Python 3.14+)",
        "(Caused by a missing line: from future import annotations)",
    ]
    for line in lines:
        assert "<" not in line and ">" not in line and "&gt;" not in line


def test_summarise_html_link():
    body = (
        'Upgrade to <a href="https://github.com/seleniumbase/SeleniumBase/'
        'releases/tag/v4.34.6">SeleniumBase 4.34.6</a> for the fix.</p>'
    )
    assert _summarise(body) == ["Upgrade to SeleniumBase 4.34.6 for the fix."]


def test_summarise_clipped_html_link():
    body = 'Upgrade to <a href=" for the fix.</p>'
    for line in _summarise(body):
        assert "<" not in line
        assert '="' not in line


def test_summarise_double_escaped_html():
    body = "&lt;code&gt;from future import annotations&lt;/code&gt; is required"
    assert _summarise(body) == ["from future import annotations is required"]


def test_summarise_rst_roles():
    raw = (
        "Fixed the client dropping trailing whitespace -- by :user:`arshsmith1`.\n"
        "Fixed :py:attr:`~aiohttp.web.StreamResponse.last_modified` rounding\n"
    )
    assert _summarise(raw) == [
        "Fixed the client dropping trailing whitespace -- by arshsmith1.",
        "Fixed last_modified rounding",
    ]
    stripped = (
        "Fixed the client dropping trailing whitespace -- by :user:arshsmith1.\n"
        "Fixed :py:attr:~aiohttp.web.StreamResponse.last_modified rounding\n"
    )
    assert _summarise(stripped) == [
        "Fixed the client dropping trailing whitespace -- by arshsmith1.",
        "Fixed last_modified rounding",
    ]


def test_summarise_unknown_rst_role():
    body = "See :ref:`the migration guide <migrating>` before upgrading"
    lines = _summarise(body)
    assert len(lines) == 1
    assert "migration guide" in lines[0]


def test_summarise_towncrier_footers():
    body = (
        "Fixed the redirect loop on empty paths\n"
        "Related issues and pull requests on GitHub:*\n"
        "13180.\n"
    )
    assert _summarise(body) == ["Fixed the redirect loop on empty paths"]


@pytest.mark.parametrize(
    "kept",
    [
        "Released the GIL when parsing large documents",
        "2.0.52 fixes the regression introduced in 2.0.51",
        "Dropped support for Python 3.8",
        "Fixed empty print ignoring the end parameter",
        "Security hardening for the redirect handler",
        "Raise an error when a < b > c is ambiguous",
    ],
)
def test_summarise_keeps_real_sentences(kept):
    assert _summarise(kept) == [kept]


def test_reflow_hard_wrapped_paragraph():
    body = (
        "**This is a big update with quite a few breaking changes. Carefully "
        "review\n"
        "the changes before upgrading. It's no problem if you can not update "
        "right now.\n"
        "The 0.8.x branch still gets bugfixes.**\n"
    )
    assert _summarise(body) == [
        "This is a big update with quite a few breaking changes.",
        "Carefully review the changes before upgrading.",
        "It's no problem if you can not update right now.",
        "The 0.8.x branch still gets bugfixes.",
    ]


def test_reflow_blank_line():
    body = (
        "The parser now rejects an empty document instead of returning None, "
        "which\n"
        "is a change in behaviour for callers that relied on it.\n"
        "\n"
        "The CLI grew a --verbose flag.\n"
    )
    assert _summarise(body) == [
        "The parser now rejects an empty document instead of returning None, "
        "which is a change in…",
        "The CLI grew a --verbose flag.",
    ]


def test_reflow_heading_boundary():
    body = (
        "The release note opens with a long enough line to look like a wrap "
        "point here\n"
        "## Highlights\n"
        "Fixed a path traversal in the archive reader.\n"
    )
    assert _summarise(body) == [
        "The release note opens with a long enough line to look like a wrap point here",
        "Highlights",
        "Fixed a path traversal in the archive reader.",
    ]


def test_reflow_list_items():
    body = (
        "- Removed the legacy client, which had been deprecated since 2.0 and "
        "unused\n"
        "- Added a --verbose flag\n"
    )
    assert _summarise(body) == [
        "Removed the legacy client, which had been deprecated since 2.0 and unused",
        "Added a --verbose flag",
    ]


def test_reflow_wrapped_list_item():
    body = (
        "- Removed castling right constants. Castling rights are now "
        "represented as a\n"
        "  bitmask of the rook square.\n"
    )
    assert _summarise(body) == [
        "Removed castling right constants.",
        "Castling rights are now represented as a bitmask of the rook square.",
    ]


def test_reflow_code_block():
    body = (
        "Configure it like this:\n"
        "\n"
        "```python\n"
        "config = Config(\n"
        "    retries=3,\n"
        ")\n"
        "```\n"
    )
    assert _summarise(body) == [
        "Configure it like this",
        "config = Config(",
        "retries=3",
        ")",
    ]


def test_reflow_sentence_then_wrap():
    body = (
        "Everything in 0.8.1 except TE support in "
        "https://github.com/m4b/goblin/pull/397 was reverted,\n"
        "due to it being technically a breaking change.\n"
        "0.8.1 was yanked from crates.\n"
    )
    assert _summarise(body) == [
        "Everything in 0.8.1 except TE support in was reverted, due to it "
        "being technically a…",
        "0.8.1 was yanked from crates.",
    ]


def test_reflow_one_record_per_line():
    body = (
        "8fa1c3d fix(core): tracer should never throw\n"
        "d332c75 chore: update dependency @types/node (#142)\n"
        "7b46da2 feat(basic-tracer): add recording Span implementation (#102)\n"
        "4186e44 feat(sdk): add No Recording Span implementation (#167)\n"
    )
    assert _summarise(body) == [
        "8fa1c3d fix(core): tracer should never throw",
        "d332c75 chore: update dependency @types/node (#142)",
        "7b46da2 feat(basic-tracer): add recording Span implementation (#102)",
        "4186e44 feat(sdk): add No Recording Span implementation (#167)",
    ]


def test_reflow_short_lines():
    body = (
        "CVE-2026-0001: this project is not affected\n"
        "Fixes CVE-2026-1234 in the certificate parser\n"
    )
    assert _summarise(body) == [
        "CVE-2026-0001: this project is not affected",
        "Fixes CVE-2026-1234 in the certificate parser",
    ]


@pytest.mark.parametrize(
    "body",
    [
        "Callers should pass a mapping, e.g. a dict, rather than a sequence.",
        "The parser accepts i.e. the same grammar as before, minus the extras.",
        "Options are read from the config, the environment, etc. Order matters.",
        "This release requires Python 3.13. Older interpreters are unsupported.",
        "The wire format is bumped to 1.0.0. Fixed the handshake while there.",
        "The rewrite was contributed by A. Turing and reviewed by others.",
    ],
)
def test_sentence_end_abbreviation(body):
    assert _summarise(body) == [body]


def test_sentence_end_split():
    body = (
        "The legacy client is gone. Callers must move to the new one, which "
        "takes the same arguments.\n"
    )
    assert _summarise(body) == [
        "The legacy client is gone.",
        "Callers must move to the new one, which takes the same arguments.",
    ]


def test_sentence_end_trailing_citation():
    body = (
        "The parser could take a long time on deeply nested input and now\n"
        "bails. [CVE-2024-3651]\n"
    )
    assert _summarise(body) == [
        "The parser could take a long time on deeply nested input and now "
        "bails. [CVE-2024-3651]"
    ]


def test_uv_lock_direct(tmp_path: Path):
    (tmp_path / "uv.lock").write_text(
        """
version = 1

[[package]]
name = "watcher"
version = "0.1.0"
source = { virtual = "." }
dependencies = [{ name = "alembic" }]

[[package]]
name = "alembic"
version = "1.18.0"
dependencies = [{ name = "mako" }]

[[package]]
name = "mako"
version = "1.3.10"
"""
    )
    project = read("pypi", tmp_path / "uv.lock")
    by_name = {d.name: d for d in project.dependencies}

    assert by_name["alembic"].direct
    assert by_name["mako"].parents == ["alembic"]
    assert "watcher" not in by_name


def test_poetry_lock_direct(tmp_path: Path):
    (tmp_path / "poetry.lock").write_text(
        """
[[package]]
name = "aiodns"
version = "4.0.4"

[package.dependencies]
pycares = ">=5.0.0,<6"

[[package]]
name = "pycares"
version = "5.0.1"
"""
    )
    project = read("pypi", tmp_path / "poetry.lock")
    by_name = {d.name: d for d in project.dependencies}

    assert by_name["aiodns"].direct
    assert by_name["pycares"].parents == ["aiodns"]


def test_corrupt_lock_file(tmp_path: Path):
    (tmp_path / "package-lock.json").write_text("{ truncated")
    assert read("npm", tmp_path / "package-lock.json") is None


def test_requirements_txt_fallback(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text(
        "# comment\n"
        "Flask==3.1.1\n"
        "requests == 2.31.0  # trailing comment\n"
        "google-genai>=1.75,<2\n"
        "-r other.txt\n"
        "--index-url https://example.invalid\n"
        "\n"
    )
    project = read("pypi", tmp_path / "requirements.txt")
    found = {d.name: d.version for d in project.dependencies}

    assert found == {"Flask": "3.1.1", "requests": "2.31.0", "google-genai": ""}
    assert all(d.direct for d in project.dependencies)


def test_requirements_txt_unpinned(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text("google-genai>=1.75,<2\n")
    project = read("pypi", tmp_path / "requirements.txt")
    assert project.dependencies[0].version == ""


def test_package_json_fallback(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "dependencies": {"expo": "~54.0.0"},
                "devDependencies": {"typescript": "^5.0.0"},
            }
        )
    )
    project = read("npm", tmp_path / "package.json")
    assert {d.name for d in project.dependencies} == {"expo", "typescript"}
    assert all(d.version == "" for d in project.dependencies)


def test_lock_file_beats_manifest(tmp_path: Path):
    (tmp_path / "package.json").write_text('{"dependencies": {"express": "^5"}}')
    (tmp_path / "package-lock.json").write_text(
        json.dumps({"packages": {"": {}, "node_modules/express": {"version": "5.2.1"}}})
    )
    assert [path.name for _, path in find(tmp_path)] == ["package-lock.json"]


def test_snapshot_payload_parents():
    from packagetrackdev.__main__ import payload, snapshot_payload
    from packagetrackdev.lockfiles import Dependency, Project

    project = Project(
        ecosystem="npm",
        source="package-lock.json",
        dependencies=[Dependency("glob", "7.2.3", parents=["rimraf"])],
    )
    assert snapshot_payload(project)["packages"][0]["parents"] == ["rimraf"]
    assert "parents" not in payload("npm", project.dependencies)["packages"][0]


def test_source_kind_per_reader(tmp_path: Path):
    from packagetrackdev.lockfiles import read

    files = {
        "package-lock.json": json.dumps(
            {"packages": {"": {}, "node_modules/ms": {"version": "2.1.3"}}}
        ),
        "uv.lock": (
            'version = 1\nrequires-python = ">=3.13"\n\n[[package]]\n'
            'name = "flask"\nversion = "3.0.0"\n'
            'source = { registry = "https://pypi.org/simple" }\n'
        ),
        "poetry.lock": '[[package]]\nname = "flask"\nversion = "3.0.0"\n',
        "Cargo.lock": (
            '[[package]]\nname = "serde"\nversion = "1.0.200"\n'
            'source = "registry+https://github.com/rust-lang/crates.io-index"\n'
        ),
        "composer.lock": json.dumps(
            {"packages": [{"name": "psr/log", "version": "3.0.2"}]}
        ),
        "requirements.txt": "flask==3.0.0\n",
        "package.json": '{"dependencies": {"left-pad": "^1.3.0"}}',
        "go.mod": "module example.com/app\nrequire github.com/lib/pq v1.12.3\n",
    }
    for filename, content in files.items():
        (tmp_path / filename).write_text(content, encoding="utf-8")
        project = read("pypi", tmp_path / filename)
        assert project is not None, filename
        assert project.source == filename


def test_snapshot_source_kind():
    from packagetrackdev.__main__ import snapshot_payload
    from packagetrackdev.lockfiles import Dependency, Project

    project = Project("pypi", "uv.lock", [Dependency("flask", "3.0.0")])
    body = snapshot_payload(project)
    assert body["source"] == "uv.lock"
    assert "/" not in body["source"]


def test_two_ecosystems_one_folder():
    from pathlib import Path

    from packagetrackdev.__main__ import project_name
    from packagetrackdev.lockfiles import Project

    folder = Path("/tmp/scrollbook")
    py = Project("pypi", "uv.lock", [])
    js = Project("npm", "package-lock.json", [])
    assert project_name(py, None, folder, many=True) == "scrollbook-pypi"
    assert project_name(js, None, folder, many=True) == "scrollbook-npm"
    assert project_name(py, None, folder, many=False) == "scrollbook"


def test_project_name_explicit():
    from pathlib import Path

    from packagetrackdev.__main__ import project_name
    from packagetrackdev.lockfiles import Project

    project = Project("pypi", "uv.lock", [])
    assert project_name(project, "chosen", Path("/tmp/x"), many=True) == "chosen"


def test_project_name_from_folder():
    from pathlib import Path

    from packagetrackdev.__main__ import project_name
    from packagetrackdev.lockfiles import Project

    project = Project("pypi", "uv.lock", [])
    assert project_name(project, None, Path("/tmp/my project!"), many=False) == (
        "my-project"
    )


def test_config_precedence(monkeypatch, tmp_path):
    from packagetrackdev import config

    written = tmp_path / "config.toml"
    written.write_text('api_key = "pkgt_fromfile"\nserver = "https://file.example"\n')
    monkeypatch.setattr(config, "CONFIG_PATH", written)

    monkeypatch.delenv(config.ENV_KEY, raising=False)
    assert config.load().api_key == "pkgt_fromfile"

    monkeypatch.setenv(config.ENV_KEY, "pkgt_fromenv")
    assert config.load().api_key == "pkgt_fromenv"
    assert config.load(api_key="pkgt_fromflag").api_key == "pkgt_fromflag"


def test_config_broken_file(monkeypatch, tmp_path):
    from packagetrackdev import config

    broken = tmp_path / "config.toml"
    broken.write_text("this is not toml [[[")
    monkeypatch.setattr(config, "CONFIG_PATH", broken)
    monkeypatch.delenv(config.ENV_KEY, raising=False)
    monkeypatch.delenv(config.ENV_SERVER, raising=False)

    settings = config.load()
    assert settings.api_key is None
    assert settings.server == config.DEFAULT_SERVER


def test_config_file_permissions(monkeypatch, tmp_path):
    import stat

    from packagetrackdev import config

    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "cfg" / "config.toml")
    path = config.save(api_key="pkgt_secret")
    mode = stat.S_IMODE(path.stat().st_mode)
    assert not mode & (stat.S_IRGRP | stat.S_IROTH), oct(mode)


def test_config_default_server(monkeypatch, tmp_path):
    from packagetrackdev import config

    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "absent.toml")
    monkeypatch.delenv(config.ENV_SERVER, raising=False)
    assert config.load().server == "https://packagetrack.dev"


def test_config_server_flag(monkeypatch, tmp_path):
    from packagetrackdev import config

    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "absent.toml")
    monkeypatch.delenv(config.ENV_SERVER, raising=False)
    assert config.load(server="http://127.0.0.1:8000").server == "http://127.0.0.1:8000"


def test_cargo_lock_workspace_members(tmp_path):
    from packagetrackdev.lockfiles import read

    (tmp_path / "Cargo.lock").write_text(
        """
version = 4

[[package]]
name = "my-app"
version = "0.1.0"
dependencies = ["serde"]

[[package]]
name = "serde"
version = "1.0.219"
source = "registry+https://github.com/rust-lang/crates.io-index"
dependencies = ["serde_derive"]

[[package]]
name = "serde_derive"
version = "1.0.219"
source = "registry+https://github.com/rust-lang/crates.io-index"
""",
        encoding="utf-8",
    )
    project = read("cargo", tmp_path / "Cargo.lock")
    names = {d.name for d in project.dependencies}
    assert names == {"serde", "serde_derive"}  # my-app dropped
    by_name = {d.name: d for d in project.dependencies}
    assert by_name["serde"].parents == []  # required by the workspace -> direct
    assert by_name["serde_derive"].parents == ["serde"]  # transitive


def test_cargo_lock_versions(tmp_path):
    from packagetrackdev.lockfiles import read

    (tmp_path / "Cargo.lock").write_text(
        '[[package]]\nname = "anyhow"\nversion = "1.0.104"\n'
        'source = "registry+https://github.com/rust-lang/crates.io-index"\n',
        encoding="utf-8",
    )
    [dep] = read("cargo", tmp_path / "Cargo.lock").dependencies
    assert dep.name == "anyhow"
    assert dep.version == "1.0.104"


def test_composer_lock_platform_requirements(tmp_path):
    from packagetrackdev.lockfiles import read

    (tmp_path / "composer.lock").write_text(
        json.dumps(
            {
                "packages": [
                    {
                        "name": "monolog/monolog",
                        "version": "v3.10.0",
                        "require": {
                            "php": ">=8.1",
                            "ext-json": "*",
                            "psr/log": "^3.0",
                        },
                    },
                    {
                        "name": "psr/log",
                        "version": "3.0.2",
                        "require": {"php": ">=8.0"},
                    },
                ],
                "packages-dev": [{"name": "phpunit/phpunit", "version": "11.5.0"}],
            }
        ),
        encoding="utf-8",
    )
    project = read("composer", tmp_path / "composer.lock")
    names = {d.name for d in project.dependencies}
    assert names == {"monolog/monolog", "psr/log", "phpunit/phpunit"}
    assert "php" not in names
    assert not any(n.startswith("ext-") for n in names)


def test_composer_lock_v_prefix(tmp_path):
    from packagetrackdev.lockfiles import read

    (tmp_path / "composer.lock").write_text(
        json.dumps({"packages": [{"name": "sy/console", "version": "v8.1.5"}]}),
        encoding="utf-8",
    )
    [dep] = read("composer", tmp_path / "composer.lock").dependencies
    assert dep.version == "v8.1.5"


def test_composer_lock_dev_direct(tmp_path):
    from packagetrackdev.lockfiles import read

    (tmp_path / "composer.lock").write_text(
        json.dumps(
            {
                "packages": [],
                "packages-dev": [{"name": "phpunit/phpunit", "version": "11.5.0"}],
            }
        ),
        encoding="utf-8",
    )
    [dep] = read("composer", tmp_path / "composer.lock").dependencies
    assert dep.parents == []


CLIENT_GO_MOD = """\
// This is a generated file. Do not edit directly.

module k8s.io/client-go

go 1.24.0

godebug default=go1.24

require (
\tgithub.com/gogo/protobuf v1.3.2
\tgithub.com/gorilla/websocket v1.5.4-0.20250319132907-e064f32e3674
\tgithub.com/peterbourgon/diskv v2.0.1+incompatible
\tgolang.org/x/net v0.38.0
\tk8s.io/api v0.34.1
\tk8s.io/klog/v2 v2.130.1
\tsigs.k8s.io/structured-merge-diff/v6 v6.3.0
)

require (
\tgithub.com/davecgh/go-spew v1.1.1 // indirect
\tgithub.com/emicklei/go-restful/v3 v3.12.2 // indirect
\tgithub.com/modern-go/concurrent v0.0.0-20180306012644-bacd9c7ef1dd // indirect
\tgopkg.in/inf.v0 v0.9.1 // indirect
)
"""


def test_gomod_require_forms(tmp_path: Path):
    from packagetrackdev.lockfiles import read

    (tmp_path / "go.mod").write_text(
        "module github.com/acme/service\n"
        "\n"
        "go 1.25.0\n"
        "\n"
        "require github.com/google/uuid v1.6.0\n"
        "\n"
        "require (\n"
        "\tgithub.com/lib/pq v1.12.3\n"
        "\tgithub.com/sirupsen/logrus v1.10.1\n"
        ")\n",
        encoding="utf-8",
    )
    project = read("go", tmp_path / "go.mod")
    assert [d.name for d in project.dependencies] == [
        "github.com/google/uuid",
        "github.com/lib/pq",
        "github.com/sirupsen/logrus",
    ]
    assert "github.com/acme/service" not in {d.name for d in project.dependencies}
    assert project.source == "go.mod"
    assert project.skipped == 0


def test_gomod_indirect(tmp_path: Path):
    from packagetrackdev.lockfiles import read

    (tmp_path / "go.mod").write_text(
        "module example.com/app\n"
        "\n"
        "require (\n"
        "\tgithub.com/spf13/viper v1.21.0\n"
        "\tgithub.com/spf13/afero v1.15.0 // indirect\n"
        ")\n",
        encoding="utf-8",
    )
    by_name = {d.name: d for d in read("go", tmp_path / "go.mod").dependencies}

    theirs = by_name["github.com/spf13/afero"]
    assert theirs.indirect is True
    assert theirs.parents == []  # not "nothing requires it": not recorded
    assert theirs.direct is False

    ours = by_name["github.com/spf13/viper"]
    assert ours.indirect is False
    assert ours.direct is True


def test_gomod_major_version_suffix(tmp_path: Path):
    from packagetrackdev.lockfiles import read

    (tmp_path / "go.mod").write_text(
        "module example.com/app\n"
        "require (\n"
        "\tgithub.com/jackc/pgx/v4 v4.18.3\n"
        "\tgo.yaml.in/yaml/v3 v3.0.4 // indirect\n"
        ")\n",
        encoding="utf-8",
    )
    by_name = {d.name: d.version for d in read("go", tmp_path / "go.mod").dependencies}
    assert by_name["github.com/jackc/pgx/v4"] == "v4.18.3"
    assert by_name["go.yaml.in/yaml/v3"] == "v3.0.4"


def test_gomod_pseudo_versions(tmp_path: Path):
    from packagetrackdev.lockfiles import read

    (tmp_path / "go.mod").write_text(
        "module example.com/app\n"
        "require (\n"
        "\tgithub.com/asmcos/requests v0.0.0-20210319030608-c839e8ae4946\n"
        "\tgithub.com/peterbourgon/diskv v2.0.1+incompatible\n"
        ")\n",
        encoding="utf-8",
    )
    versions = {d.name: d.version for d in read("go", tmp_path / "go.mod").dependencies}
    assert versions["github.com/asmcos/requests"] == (
        "v0.0.0-20210319030608-c839e8ae4946"
    )
    assert versions["github.com/peterbourgon/diskv"] == "v2.0.1+incompatible"


def test_gomod_replace(tmp_path: Path, caplog):
    from packagetrackdev.lockfiles import read

    (tmp_path / "go.mod").write_text(
        "module example.com/app\n"
        "\n"
        "require (\n"
        "\tgithub.com/lib/pq v1.12.3\n"
        "\tgithub.com/acme/widget v1.0.0\n"
        "\tgithub.com/sirupsen/logrus v1.10.1\n"
        ")\n"
        "\n"
        "replace github.com/acme/widget => ../widget\n"
        "\n"
        "replace (\n"
        "\tgithub.com/sirupsen/logrus v1.10.1 => github.com/acme/logrus v1.10.2\n"
        ")\n",
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING, logger="packagetrackdev.lockfiles"):
        project = read("go", tmp_path / "go.mod")

    assert [d.name for d in project.dependencies] == ["github.com/lib/pq"]
    assert project.skipped == 2  # never a silent shrink
    assert "github.com/acme/widget" in caplog.text
    assert "github.com/sirupsen/logrus" in caplog.text
    assert "replaced" in project.note


def test_gomod_other_directives(tmp_path: Path):
    from packagetrackdev.lockfiles import read

    (tmp_path / "go.mod").write_text(
        "module example.com/app\n"
        "\n"
        "go 1.24.4\n"
        "toolchain go1.24.6\n"
        "godebug default=go1.24\n"
        "tool golang.org/x/tools/cmd/stringer\n"
        "\n"
        "require github.com/google/uuid v1.6.0\n"
        "\n"
        "exclude github.com/bad/module v1.0.0\n"
        "exclude (\n"
        "\tgithub.com/bad/other v2.0.0\n"
        ")\n"
        "\n"
        "retract v1.0.1\n"
        "retract (\n"
        "\tv1.0.2\n"
        "\t[v1.1.0, v1.2.0]\n"
        ")\n",
        encoding="utf-8",
    )
    project = read("go", tmp_path / "go.mod")
    assert [d.name for d in project.dependencies] == ["github.com/google/uuid"]
    assert project.skipped == 0  # they are directives, not unreadable lines


def test_gomod_comments_and_blank_lines(tmp_path: Path):
    from packagetrackdev.lockfiles import read

    (tmp_path / "go.mod").write_text(
        "// generated, do not edit\n"
        "\n"
        "module example.com/app // the project itself\n"
        "\n"
        "// the direct ones\n"
        "require (\n"
        "\n"
        "\t// pinned deliberately, see PR 412\n"
        "\tgithub.com/google/uuid v1.6.0 // keep\n"
        "\n"
        "\tgithub.com/lib/pq v1.12.3 //indirect\n"
        ")\n"
        "\n",
        encoding="utf-8",
    )
    project = read("go", tmp_path / "go.mod")
    by_name = {d.name: d for d in project.dependencies}
    assert set(by_name) == {"github.com/google/uuid", "github.com/lib/pq"}
    assert by_name["github.com/google/uuid"].indirect is False  # "// keep"
    assert by_name["github.com/lib/pq"].indirect is True
    assert project.skipped == 0


def test_gomod_real_file(tmp_path: Path):
    from packagetrackdev.lockfiles import read

    (tmp_path / "go.mod").write_text(CLIENT_GO_MOD, encoding="utf-8")
    project = read("go", tmp_path / "go.mod")

    assert project.skipped == 0
    assert len(project.dependencies) == 11
    assert len(project.direct) == 7
    assert "k8s.io/client-go" not in {d.name for d in project.dependencies}
    indirect = {d.name for d in project.dependencies if d.indirect}
    assert indirect == {
        "github.com/davecgh/go-spew",
        "github.com/emicklei/go-restful/v3",
        "github.com/modern-go/concurrent",
        "gopkg.in/inf.v0",
    }
    assert not any(d.parents for d in project.dependencies)


def test_gomod_malformed_require(tmp_path: Path):
    from packagetrackdev.lockfiles import read

    (tmp_path / "go.mod").write_text(
        "module example.com/app\n"
        "require (\n"
        "\tgithub.com/google/uuid v1.6.0\n"
        "\tgithub.com/broken/entry\n"
        "\tgithub.com/broken/other latest\n"
        ")\n"
        "wat github.com/nonsense v1.0.0\n",
        encoding="utf-8",
    )
    project = read("go", tmp_path / "go.mod")
    assert [d.name for d in project.dependencies] == ["github.com/google/uuid"]
    assert project.skipped == 3


def test_gomod_absurd_module_path(tmp_path: Path):
    from packagetrackdev.lockfiles import MAX_NAME_CHARS, read

    huge = "github.com/acme/" + "x" * MAX_NAME_CHARS
    (tmp_path / "go.mod").write_text(
        f"module example.com/app\nrequire (\n\t{huge} v1.0.0\n"
        "\tgithub.com/google/uuid v1.6.0\n)\n",
        encoding="utf-8",
    )
    project = read("go", tmp_path / "go.mod")
    assert [d.name for d in project.dependencies] == ["github.com/google/uuid"]
    assert project.skipped == 1


def test_gomod_wire_schema(tmp_path: Path):
    from packagetrackdev.lockfiles import MAX_NAME_CHARS, MAX_VERSION_CHARS, read

    longest_path = (
        "github.com/GoogleCloudPlatform/opentelemetry-operations-go/"
        "internal/resourcemapping"
    )
    longest_version = "v1.0.3-0.20250322232337-35a7c28c31ee+incompatible"
    (tmp_path / "go.mod").write_text(
        f"module example.com/app\nrequire {longest_path} {longest_version}\n",
        encoding="utf-8",
    )
    [dep] = read("go", tmp_path / "go.mod").dependencies
    assert dep.name == longest_path
    assert len(dep.name) <= MAX_NAME_CHARS
    assert len(dep.version) <= MAX_VERSION_CHARS


def test_go_sum_ignored(tmp_path: Path):
    from packagetrackdev.lockfiles import detect, find

    (tmp_path / "go.mod").write_text(
        "module example.com/app\nrequire github.com/lib/pq v1.12.3\n", encoding="utf-8"
    )
    go_sum = (
        "github.com/lib/pq v1.10.9 h1:YXG7RB+JIjhP29X+OtkiDnYaXQwpS4JEWq7dtCCRUEw=\n"
        "github.com/lib/pq v1.10.9/go.mod "
        "h1:AlVN5x4E4T544tWzH6hKfbfQvm3HdbOxrmggDNAPY9o=\n"
        "github.com/lib/pq v1.12.3 h1:jkNSN0RRTKuXZ5o8mVAOJ4vPMkzKfIGmwYVBmqEvUOo=\n"
    )
    (tmp_path / "go.sum").write_text(go_sum, encoding="utf-8")

    assert [path.name for _, path in find(tmp_path)] == ["go.mod"]
    assert detect(go_sum) is None
    assert detect(go_sum, "go.sum") is None


def test_gomod_before_1_17(tmp_path: Path):
    from packagetrackdev.lockfiles import read

    (tmp_path / "go.mod").write_text(
        "module example.com/app\ngo 1.16\nrequire github.com/lib/pq v1.12.3\n",
        encoding="utf-8",
    )
    project = read("go", tmp_path / "go.mod")
    assert "incomplete" in project.note
    assert "1.16" in project.note


def test_snapshot_payload_indirect():
    from packagetrackdev.__main__ import snapshot_payload
    from packagetrackdev.lockfiles import Dependency, Project

    project = Project(
        ecosystem="go",
        source="go.mod",
        dependencies=[
            Dependency("github.com/spf13/viper", "v1.21.0"),
            Dependency("github.com/spf13/afero", "v1.15.0", indirect=True),
        ],
    )
    packages = {p["name"]: p for p in snapshot_payload(project)["packages"]}
    assert packages["github.com/spf13/afero"]["indirect"] is True
    assert packages["github.com/spf13/afero"]["parents"] == []
    assert packages["github.com/spf13/viper"]["indirect"] is False
