"""The customer-facing command."""

import json
import logging
import sys
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
    names = {d.name for d in project.dependencies}
    assert names == {"express"}
    assert "@myapp/ui" not in names and "packages/ui" not in names


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


def test_summarise_drops_a_release_please_version_heading():
    body = "## 1.5.0 (2026-09-10)\n\n* add auto mode tool permissions\n"
    assert _summarise(body) == ["add auto mode tool permissions"]


def test_summarise_drops_an_rst_anchor():
    body = ".. _v37-0-3:\n\n* fix a crash when parsing an empty certificate\n"
    assert _summarise(body) == ["fix a crash when parsing an empty certificate"]
    assert _summarise(".. _v50-0-0\n\n* drop support for OpenSSL 1.1.1\n") == [
        "drop support for OpenSSL 1.1.1"
    ]


_CLICK_850_LINKS = (
    '<p>PyPI: <a href="https://pypi.org/project/click/8.5.0/">'
    "https://pypi.org/project/click/8.5.0/</a><br>\n"
    'Changes:  <a href="https://click.palletsprojects.com/page/changes/#version-8-5-0">'
    "https://click.palletsprojects.com/page/changes/#version-8-5-0</a><br>\n"
    'Milestone <a href="https://github.com/pallets/click/milestone/33">'
    "https://github.com/pallets/click/milestone/33</a></p>\n"
)
_CLICK_841_ECHO = (
    "<li>Fix empty byte-string handling in echo. "
    '<a href="https://github.com/pallets/click/issues/3487">#3487</a></li>\n'
)


def test_summarise_drops_link_labels():
    body = _CLICK_850_LINKS + "<ul>\n" + _CLICK_841_ECHO + "</ul>\n"
    assert _summarise(body) == ["Fix empty byte-string handling in echo. #3487"]
    body = (
        "  continue to be escaped by the SAX `XMLGenerator`.\n"
        "  Advisory: https://fluidattacks.com/advisories/mono\n"
    )
    assert _summarise(body) == ["continue to be escaped by the SAX XMLGenerator."]


def test_summarise_keeps_a_label_with_no_link():
    body = "Improvements:\n\n- Add ignore for `avoid_as` lint to generated code.\n"
    assert _summarise(body) == [
        "Improvements",
        "Add ignore for avoid_as lint to generated code.",
    ]


def test_summarise_keeps_a_wrapped_word_before_a_url():
    body = (
        "  This may contain minor breaking changes so we advise careful testing and\n"
        "  reviewing https://urllib3.readthedocs.io/en/latest/v2-migration-guide.html\n"
        "  prior to upgrading.\n"
    )
    lines = _summarise(body)
    assert len(lines) == 1
    assert "careful testing and reviewing prior" in lines[0]


def test_summarise_joins_an_html_wrapped_sentence():
    body = (
        "<li>Fix Fish shell completion broken in <code>8.4.0</code> by "
        '<a href="https://github.com/pallets/click/pull/3126">#3126</a>. '
        "Newlines and<br>\n"
        "tabs in option help text are now escaped, keeping the original "
        "completion<br>\n"
        "format while still supporting multi-line help. "
        '<a href="https://github.com/pallets/click/issues/3502">#3502</a><br>\n'
        '<a href="https://github.com/pallets/click/issues/3043">#3043</a> '
        '<a href="https://github.com/pallets/click/pull/3504">#3504</a> '
        '<a href="https://github.com/pallets/click/pull/3508">#3508</a></li>\n'
    )
    lines = _summarise(body)
    assert lines[0] == "Fix Fish shell completion broken in 8.4.0 by #3126."
    assert lines[1].startswith(
        "Newlines and tabs in option help text are now escaped, keeping the "
        "original completion"
    )
    body = (
        "<li>Add built-in shell completion support for PowerShell "
        "(Windows PowerShell<br>\n"
        "5.1+ and pwsh 7+) alongside the existing <code>bash</code>, "
        "<code>zsh</code>, and <code>fish</code><br>\n"
        "completers. Use <code>_FOO_BAR_COMPLETE=powershell_source foo-bar</code> "
        "to generate<br>\n"
        "the completion script. "
        '<a href="https://github.com/pallets/click/issues/2672">#2672</a> '
        '<a href="https://github.com/pallets/click/pull/3637">#3637</a></li>\n'
    )
    lines = _summarise(body)
    assert lines[0].startswith(
        "Add built-in shell completion support for PowerShell "
        "(Windows PowerShell 5.1+ and pwsh 7+)"
    )
    assert lines[1].startswith(
        "Use _FOO_BAR_COMPLETE=powershell_source foo-bar to generate the completion"
    )


def test_summarise_keeps_html_records_apart():
    body = (
        '<li>Fix <a href="https://en.wikipedia.org/wiki/ReDoS">ReDoS</a> in certain '
        'cases (<a href="https://github.com/chalk/ansi-regex/pull/37">#37</a>)<br>\n'
        "You are only really affected if you run the regex on untrusted user input "
        "in a server context, which it's very unlikely anyone is doing, since this "
        "regex is mainly used in command-line tools.</li>\n"
    )
    lines = _summarise(body)
    assert lines[0] == "Fix ReDoS in certain cases (#37)"
    assert lines[1].startswith("You are only really affected")
    body = (
        '<p>Revert "Revert fast-uri change '
        '(<a href="https://github.com/ajv-validator/ajv/pull/2444">#2444</a>)" by '
        '<a href="https://github.com/gurgunday">@gurgunday</a> in '
        '<a href="https://github.com/ajv-validator/ajv/pull/2448">#2448</a><br>\n'
        "fix: ignore new eslint error for @typescript-eslint/no-extraneous-class by "
        '<a href="https://github.com/jasoniangreen">@jasoniangreen</a> in '
        '<a href="https://github.com/ajv-validator/ajv/pull/2455">#2455</a><br>\n'
        "docs: clarify behaviour of addVocabulary by "
        '<a href="https://github.com/jasoniangreen">@jasoniangreen</a> in '
        '<a href="https://github.com/ajv-validator/ajv/pull/2454">#2454</a><br>\n'
    )
    lines = _summarise(body)
    assert len(lines) == 3
    assert lines[1].startswith("fix: ignore new eslint error")
    assert lines[2].startswith("docs: clarify behaviour of addVocabulary")


def test_summarise_rst_role_rendered_as_html():
    body = (
        "<li>Use :func:<code>shlex.split</code> to split pager and editor "
        "commands into <code>argv</code><br>\n"
        "lists for :class:<code>subprocess.Popen</code>, removing "
        "<code>shell=True</code>.<br>\n"
        '<a href="https://github.com/pallets/click/issues/1026">#1026</a> '
        '<a href="https://github.com/pallets/click/pull/1477">#1477</a> '
        '<a href="https://github.com/pallets/click/pull/2775">#2775</a></li>\n'
    )
    assert _summarise(body)[0].startswith(
        "Use shlex.split to split pager and editor commands into argv lists for "
        "subprocess.Popen"
    )
    body = (
        "<p>Fixed a race condition in :py:class:<code>~aiohttp.TCPConnector</code> "
        "where closing the connector while a DNS resolution was in-flight could "
        "raise :py:exc:<code>AttributeError</code> instead of "
        ":py:exc:<code>~aiohttp.ClientConnectionError</code> -- by "
        ":user:<code>goingforstudying-ctrl</code>.</p>\n"
    )
    assert _summarise(body)[0].startswith(
        "Fixed a race condition in TCPConnector where closing the connector"
    )


def test_summarise_keeps_a_role_named_in_prose():
    body = (
        "<p>based on the database name alone, where only <code>:memory:</code> "
        "or an empty<br>\n"
        "database name indicate a memory database; interpreting the query "
        "string<br>\n"
    )
    line = _summarise(body)[0]
    assert "memory:" in line
    assert "or an empty database name" in line
    body = (
        "#12562 : Possible typos in using the :user: RST role is now being linted\n"
        "through the pre-commit tool integration – by @webknjaz .\n"
    )
    assert "user: RST role is now being linted" in _summarise(body)[0]


def test_summarise_drops_a_version_heading_with_a_written_date():
    body = (
        "<h2>0.28.1 (6th December, 2024)</h2>\n<ul>\n"
        "<li>Fix SSL case where <code>verify=False</code> together with client "
        "side certificates.</li>\n</ul>\n"
    )
    assert _summarise(body) == [
        "Fix SSL case where verify=False together with client side certificates."
    ]
    body = (
        "<h2>1.0.5 (March 27th, 2024)</h2>\n<ul>\n"
        "<li>Handle <code>EndOfStream</code> for anyio backend. "
        '(<a href="https://github.com/encode/httpcore/pull/899">#899</a>)</li>\n'
    )
    assert _summarise(body) == ["Handle EndOfStream for anyio backend. (#899)"]


def test_summarise_keeps_a_version_line_that_is_not_a_heading():
    body = "<h2>1.13.0 (Unreleased)</h2>\n<p>UPGRADE NOTES:</p>\n"
    assert _summarise(body)[0] == "1.13.0 (Unreleased)"
    body = (
        "### v1.9.0 (2021-12-31) Changes\n\n"
        "* Apply `update_forward_refs` to `Config.json_encodes` prevent name "
        "clashes in types defined via strings, "
        "[#3583](https://github.com/pydantic/pydantic/pull/3583) by @samuelcolvin\n"
    )
    assert _summarise(body)[0] == "v1.9.0 (2021-12-31) Changes"


def test_summarise_never_ends_on_a_heading():
    body = (
        "### Features\n\n"
        "* add a --json flag to the report command\n"
        "* support Python 3.14\n"
        "* stream large lock files\n"
        "* read uv.lock workspaces\n\n"
        "### Bug Fixes\n\n"
        "* do not crash on an empty uv.lock\n"
    )
    assert _summarise(body) == [
        "Features",
        "add a --json flag to the report command",
        "support Python 3.14",
        "stream large lock files",
        "read uv.lock workspaces",
    ]
    assert _summarise("* fix the parser\n\n### Other changes\n") == ["fix the parser"]


def test_summarise_an_issue_reference_is_not_a_heading():
    body = (
        "### Bug Fixes\n\n"
        "-\n#10452 : Fix a race when creating junitxml reports.\n\n"
        "-\n#10457 : Show the test location for a skip inside a fixture.\n"
    )
    assert _summarise(body) == [
        "Bug Fixes",
        "10452: Fix a race when creating junitxml reports.",
        "10457: Show the test location for a skip inside a fixture.",
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


def test_a_requirements_line_counts_only_whole(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text(
        "django==5.0\n"
        "SECRET_KEY=abc123\n"
        "DEBUG=true\n"
        "https://example.com/pkg-1.0.whl\n"
        "git+https://github.com/x/y.git#egg=y\n"
        "C:\\wheels\\foo.whl\n"
        "name: value\n"
        "some words here\n"
        "requests @ https://example.com/requests-2.32.0.whl\n"
        'pkg[extra] @ https://example.com/p.whl ; python_version>"3"\n'
        "flask[async]>=2.0\n"
        'numpy; python_version<"3.12"\n'
        "Django >= 4.2, < 5\n"
        "pytest\n"
        "attrs==23.1.0 \\\n"
        "    --hash=sha256:abc\n",
        encoding="utf-8",
    )
    project = read("pypi", tmp_path / "requirements.txt")

    assert [(d.name, d.version) for d in project.dependencies] == [
        ("django", "5.0"),
        ("requests", ""),
        ("pkg", ""),
        ("flask", ""),
        ("numpy", ""),
        ("Django", ""),
        ("pytest", ""),
        ("attrs", "23.1.0"),
    ]
    assert project.skipped == 8
    for junk in ("SECRET_KEY", "DEBUG", "https", "git", "C", "name", "some"):
        assert junk not in {d.name for d in project.dependencies}, junk


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


@pytest.mark.parametrize(
    ("spec", "version"),
    [
        ("7.29.0", "7.29.0"),
        ("=7.29.0", "7.29.0"),
        ("v7.29.0", "7.29.0"),
        (" 7.29.0 ", "7.29.0"),
        ("1.0.0-beta.2", "1.0.0-beta.2"),
        ("1.2.3+build.5", "1.2.3"),
        ("^7.29.0", ""),
        ("~7.29.0", ""),
        ("7.29.x", ""),
        ("7.x", ""),
        ("7.29", ""),
        ("*", ""),
        ("", ""),
        ("latest", ""),
        (">=7.29.0", ""),
        ("<8", ""),
        ("7.29.0 - 8.0.0", ""),
        ("7.29.0 || 8.0.0", ""),
        ("npm:undici@7.29.0", ""),
        ("file:../local", ""),
        ("git+https://github.com/nodejs/undici.git#v7.29.0", ""),
        ("workspace:*", ""),
        ("workspace:7.29.0", ""),
    ],
)
def test_package_json_exact_pin(tmp_path: Path, spec, version):
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"undici-types": spec}})
    )
    project = read("npm", tmp_path / "package.json")
    assert [(d.name, d.version) for d in project.dependencies] == [
        ("undici-types", version)
    ]


def test_package_json_pins_and_ranges(tmp_path: Path):
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "dependencies": {"undici-types": "7.29.0", "expo": "~54.0.0"},
                "devDependencies": {"typescript": "5.9.2"},
            }
        )
    )
    project = read("npm", tmp_path / "package.json")
    assert {d.name: d.version for d in project.dependencies} == {
        "expo": "",
        "typescript": "5.9.2",
        "undici-types": "7.29.0",
    }


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


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="chmod cannot restrict group/other read bits on NTFS; group/other "
    "read on Windows is a filesystem limitation of the saved key, not a "
    "regression this test can catch there",
)
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


def _push_line(monkeypatch, capsys, result: dict) -> str:
    """The first line `push` prints for a server answer, nothing else faked."""
    return _push_output(monkeypatch, capsys, result)[0]


def _push_output(monkeypatch, capsys, result: dict) -> list[str]:
    """Every line `push` prints to stdout for a server answer."""
    import argparse
    from types import SimpleNamespace

    import packagetrackdev.__main__ as cli_main

    project = SimpleNamespace(ecosystem="pypi", source="uv.lock", dependencies=[])
    monkeypatch.setattr(cli_main, "_projects_or_exit", lambda folder, eco: [project])
    monkeypatch.setattr(cli_main, "push", lambda *args, **kwargs: result)
    monkeypatch.setattr(
        cli_main.config,
        "load",
        lambda **kwargs: SimpleNamespace(api_key="pkgt_x", server="https://pt.test"),
    )
    args = argparse.Namespace(
        api_key=None,
        server=None,
        project=Path("."),
        ecosystem=None,
        dry_run=False,
        name="repro-unmeasured",
    )
    capsys.readouterr()
    assert cli_main.cmd_push(args) == 0
    return capsys.readouterr().out.splitlines()


def _answer(**fields) -> dict:
    base = {
        "project": "repro-unmeasured",
        "stored": 6,
        "behind": 0,
        "withdrawn": 0,
        "unpinned": 0,
        "url": "/app/projects/repro-unmeasured",
        "rules": [],
        "unmeasured_note": None,
    }
    return {**base, **fields}


def test_a_first_push_nobody_compared_does_not_say_zero_behind(monkeypatch, capsys):
    line = _push_line(monkeypatch, capsys, _answer(not_compared=6, being_looked_up=6))
    assert line == (
        "repro-unmeasured: 6 packages from uv.lock, none compared yet, "
        "6 being looked up; push again when that finishes"
    )
    assert "of yours behind" not in line


def test_the_push_line_names_what_was_not_compared_beside_the_count(
    monkeypatch, capsys
):
    looking = _push_line(
        monkeypatch,
        capsys,
        _answer(stored=3, behind=1, not_compared=2, being_looked_up=2),
    )
    assert looking == (
        "repro-unmeasured: 3 packages from uv.lock, 1 of yours behind, "
        "2 being looked up; push again when that finishes"
    )
    denied = _push_line(
        monkeypatch,
        capsys,
        _answer(stored=3, behind=1, not_compared=2, being_looked_up=0),
    )
    assert denied == (
        "repro-unmeasured: 3 packages from uv.lock, 1 of yours behind, "
        "2 could not be compared"
    )


def test_the_rate_limit_warning_names_the_count(monkeypatch, capsys):
    """The push is stored; the lookups the hourly ceiling refused are said on
    stderr, and nothing promises a time."""
    import argparse
    from types import SimpleNamespace

    import packagetrackdev.__main__ as cli_main

    project = SimpleNamespace(ecosystem="pypi", source="uv.lock", dependencies=[])
    monkeypatch.setattr(cli_main, "_projects_or_exit", lambda folder, eco: [project])
    monkeypatch.setattr(
        cli_main,
        "push",
        lambda *a, **k: _answer(lookups_refused=2),
    )
    monkeypatch.setattr(
        cli_main.config,
        "load",
        lambda **kwargs: SimpleNamespace(api_key="pkgt_x", server="https://pt.test"),
    )
    args = argparse.Namespace(
        api_key=None,
        server=None,
        project=Path("."),
        ecosystem=None,
        dry_run=False,
        name="repro-unmeasured",
    )
    capsys.readouterr()
    assert cli_main.cmd_push(args) == 0, "a refused lookup does not fail the push"
    err = capsys.readouterr().err
    assert (
        "warning: rate limit: PackageTrack's lookup queue is full for this hour "
        "(2 not looked up). Push again later."
    ) in err


def test_no_rate_limit_warning_without_a_refusal(monkeypatch, capsys):
    _push_line(monkeypatch, capsys, _answer())
    assert "rate limit" not in capsys.readouterr().err


def test_a_server_without_the_fields_gets_the_line_it_always_got(monkeypatch, capsys):
    line = _push_line(monkeypatch, capsys, _answer())
    assert line == "repro-unmeasured: 6 packages from uv.lock, 0 of yours behind"


def test_a_push_that_made_the_project_says_so(monkeypatch, capsys):
    """A renamed folder used to become a second project in silence."""
    line = _push_line(monkeypatch, capsys, _answer(created=True))
    assert line == (
        "repro-unmeasured: new project, 6 packages from uv.lock, 0 of yours behind"
    )


def test_a_new_project_gets_no_advice_line(monkeypatch, capsys):
    """Only the fact: the generic "if it exists under another name" line fired
    on projects that were new on purpose."""
    out = _push_output(monkeypatch, capsys, _answer(created=True))
    assert out[0].startswith("repro-unmeasured: new project, ")
    assert len(out) == 2
    assert out[1] == "  https://pt.test/app/projects/repro-unmeasured"


def test_a_push_that_replaced_the_project_reads_as_it_always_did(monkeypatch, capsys):
    out = _push_output(monkeypatch, capsys, _answer(created=False))
    assert out[0] == "repro-unmeasured: 6 packages from uv.lock, 0 of yours behind"
    assert len(out) == 2


def _push_streams(monkeypatch, capsys, result: dict) -> tuple[list[str], list[str]]:
    """Both streams `push` writes for a server answer: (stdout, stderr)."""
    _push_output(monkeypatch, capsys, result)
    import argparse

    import packagetrackdev.__main__ as cli_main

    args = argparse.Namespace(
        api_key=None,
        server=None,
        project=Path("."),
        ecosystem=None,
        dry_run=False,
        name="repro-unmeasured",
    )
    assert cli_main.cmd_push(args) == 0
    captured = capsys.readouterr()
    return captured.out.splitlines(), captured.err.splitlines()


def test_an_unchanged_push_says_so_in_the_line(monkeypatch, capsys):
    """The server wrote no history entry; the line says why nothing moved."""
    line = _push_line(monkeypatch, capsys, _answer(created=False, unchanged=True))
    assert line == (
        "repro-unmeasured: 6 packages from uv.lock, no change since the last "
        "push, 0 of yours behind"
    )


def test_a_set_another_project_holds_is_a_note_on_stderr(monkeypatch, capsys):
    """The push stands; the note names the project and how to update it."""
    out, err = _push_streams(
        monkeypatch,
        capsys,
        _answer(
            created=True,
            similar_to=[{"name": "shop", "overlap": 1.0}],
        ),
    )
    assert len(out) == 2, "stdout keeps its two lines"
    assert err == [
        "  note: project 'shop' holds the same dependency set (100% of the "
        "packages in common); to update that one instead, push with --name shop"
    ]


def test_several_projects_holding_the_set_are_one_more_line(monkeypatch, capsys):
    """The closest gets the sentence; four copies used to be four notes."""
    _, err = _push_streams(
        monkeypatch,
        capsys,
        _answer(
            created=True,
            similar_to=[
                {"name": "shop", "overlap": 1.0},
                {"name": "shop-old", "overlap": 1.0},
                {"name": "shop-agent", "overlap": 0.95},
            ],
        ),
    )
    assert len(err) == 2
    assert err[0].startswith("  note: project 'shop' holds the same dependency set")
    assert err[1] == "  note: also holding it: 'shop-old', 'shop-agent'"


def test_a_server_without_similar_to_prints_no_note(monkeypatch, capsys):
    out, err = _push_streams(monkeypatch, capsys, _answer(created=True))
    assert err == []
    assert out[0].startswith("repro-unmeasured: new project, ")


class _FakeClient:
    """An httpx.Client that hands out prepared answers, one per request."""

    def __init__(self, answers):
        self._answers = list(answers)
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, json=None, headers=None):
        import httpx

        self.sent.append(json)
        answer = self._answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        status, body = answer
        return httpx.Response(status, json=body, request=httpx.Request("POST", url))


def _run_check(monkeypatch, capsys, projects, answers, show_all=False):
    """Run `check` against prepared answers; no socket is opened."""
    import argparse
    from types import SimpleNamespace

    import packagetrackdev.__main__ as cli_main

    client = _FakeClient(answers)
    monkeypatch.setattr(cli_main.httpx, "Client", lambda **kwargs: client)
    monkeypatch.setattr(cli_main, "_projects_or_exit", lambda folder, eco: projects)
    monkeypatch.setattr(
        cli_main.config,
        "load",
        lambda **kwargs: SimpleNamespace(api_key=None, server="https://pt.test"),
    )
    args = argparse.Namespace(
        server=None,
        project=Path("."),
        ecosystem=None,
        dry_run=False,
        all=show_all,
    )
    capsys.readouterr()
    code = cli_main.cmd_check(args)
    captured = capsys.readouterr()
    return code, captured, client


def _query(monkeypatch, project, answers):
    """Ask about one project against prepared answers; no socket is opened."""
    import packagetrackdev.__main__ as cli_main

    client = _FakeClient(answers)
    monkeypatch.setattr(cli_main.httpx, "Client", lambda **kwargs: client)
    return cli_main.query("https://pt.test", project)


def _project(deps, ecosystem="pypi", source="uv.lock", **fields):
    from packagetrackdev.lockfiles import Project

    return Project(
        ecosystem=ecosystem, source=source, dependencies=list(deps), **fields
    )


def _row(name, installed, **fields):
    base = {
        "name": name,
        "ecosystem": "pypi",
        "installed": installed,
        "known": True,
        "installed_known": True,
        "latest": "2.0.0",
        "latest_stable": "2.0.0",
        "versions_behind": 3,
        "installed_yanked": False,
        "installed_yanked_reason": None,
        "installed_deprecated": False,
        "installed_deprecated_reason": None,
        "notes": [],
    }
    return {**base, **fields}


def test_check_keeps_the_answers_a_later_batch_lost(monkeypatch):
    import httpx
    import packagetrackdev.__main__ as cli_main

    monkeypatch.setattr(cli_main, "CHUNK", 1)
    project = _project(
        [
            Dependency(name="django", version="4.2.1"),
            Dependency(name="flask", version="3.0.0"),
        ]
    )
    result = _query(
        monkeypatch,
        project,
        [
            (200, {"packages": [_row("django", "4.2.1")]}),
            httpx.ConnectError("no route to host"),
        ],
    )
    kept, lost = result.packages
    assert (kept.comparison, kept.versions_behind) == ("compared", 3)
    assert (lost.comparison, lost.versions_behind) == ("not_answered", None)
    (error,) = result.errors
    assert error.code == "server_unreachable"
    assert error.scope["batch"] == {"number": 1, "packages": 1}


def test_check_never_reads_an_unmeasured_package_as_current(monkeypatch):
    project = _project(
        [
            Dependency(name="django", version="4.2.1"),
            Dependency(name="internal-thing", version="1.0.0"),
            Dependency(name="flask", version=""),
            Dependency(name="numpy", version="0.0.0+local"),
        ]
    )
    result = _query(
        monkeypatch,
        project,
        [
            (
                200,
                {
                    "packages": [
                        _row("django", "4.2.1", versions_behind=0),
                        _row(
                            "internal-thing",
                            "1.0.0",
                            known=False,
                            installed_known=False,
                            latest=None,
                            latest_stable=None,
                            versions_behind=None,
                        ),
                        _row("flask", "", installed_known=False, versions_behind=None),
                        _row(
                            "numpy",
                            "0.0.0+local",
                            installed_known=False,
                            versions_behind=None,
                        ),
                    ]
                },
            )
        ],
    )
    assert not result.errors
    states = {
        p.requested.name: (p.comparison, p.versions_behind) for p in result.packages
    }
    assert states == {
        "django": ("compared", 0),
        "internal-thing": ("unknown_package", None),
        "flask": ("unpinned", None),
        "numpy": ("unplaced_version", None),
    }


def test_check_keeps_two_installed_versions_of_one_package_apart(
    monkeypatch, tmp_path: Path
):
    (tmp_path / "package-lock.json").write_text(
        json.dumps(
            {
                "packages": {
                    "": {"dependencies": {"glob": "^13.0.0"}},
                    "node_modules/glob": {"version": "13.0.6"},
                    "node_modules/rimraf": {"version": "5.0.0"},
                    "node_modules/rimraf/node_modules/glob": {"version": "7.2.3"},
                }
            }
        )
    )
    project = read("npm", tmp_path / "package-lock.json")
    rows = [
        _row(dep.name, dep.version, versions_behind=0 if dep.version == "13.0.6" else 9)
        for dep in project.dependencies
    ]
    result = _query(monkeypatch, project, [(200, {"packages": rows})])
    assert not result.errors
    globs = [
        (p.requested.version, p.versions_behind)
        for p in result.packages
        if p.name == "glob"
    ]
    assert sorted(globs) == [("13.0.6", 0), ("7.2.3", 9)]


def test_check_uses_the_name_the_server_normalized(monkeypatch):
    project = _project([Dependency(name="Flask", version="3.0.0")])
    result = _query(
        monkeypatch, project, [(200, {"packages": [_row("flask", "3.0.0")]})]
    )
    (package,) = result.packages
    assert (package.name, package.requested.name) == ("flask", "Flask")
    assert package.comparison == "compared"


def test_check_will_not_pair_an_answer_it_cannot_place(monkeypatch, capsys):
    project = _project(
        [
            Dependency(name="django", version="4.2.1"),
            Dependency(name="flask", version="3.0.0"),
        ]
    )
    answers = [(200, {"packages": [_row("flask", "3.0.0"), _row("celery", "5.0.0")]})]
    result = _query(monkeypatch, project, list(answers))
    states = {p.requested.name: p.comparison for p in result.packages}
    assert states == {"django": "not_answered", "flask": "compared"}
    assert [e.code for e in result.errors] == ["unmatched_answers"]
    code, out, _ = _run_check(monkeypatch, capsys, [project], answers)
    assert code == 2
    assert "error:" in out.err


def test_check_text_output_is_unchanged(monkeypatch, capsys):
    project = _project(
        [
            Dependency(name="django", version="4.2.1"),
            Dependency(name="sqlparse", version="0.4.0", parents=["django"]),
        ]
    )
    code, out, _ = _run_check(
        monkeypatch,
        capsys,
        [project],
        [
            (
                200,
                {
                    "packages": [
                        _row(
                            "django",
                            "4.2.1",
                            versions_behind=3,
                            notes=[{"version": "5.0.0", "body": "Dropped Python 3.8."}],
                        ),
                        _row("sqlparse", "0.4.0", versions_behind=1),
                    ]
                },
            )
        ],
    )
    assert code == 0
    assert out.out.splitlines()[1] == "uv.lock: 2 packages, 1 of them yours."
    assert "Your dependencies, behind:" in out.out
    assert "django 4.2.1 -> 2.0.0   3 behind" in out.out
    assert "    Dropped Python 3.8." in out.out
    assert "1 packages you did not ask for are also behind." in out.out


def test_check_text_says_all_current_only_when_everything_was_compared(
    monkeypatch, capsys
):
    project = _project(
        [
            Dependency(name="django", version="4.2.1"),
            Dependency(name="internal-thing", version="1.0.0"),
        ]
    )
    code, out, _ = _run_check(
        monkeypatch,
        capsys,
        [project],
        [
            (
                200,
                {
                    "packages": [
                        _row("django", "4.2.1", versions_behind=0),
                        _row(
                            "internal-thing",
                            "1.0.0",
                            known=False,
                            versions_behind=None,
                            installed_known=False,
                        ),
                    ]
                },
            )
        ],
    )
    assert code == 0
    assert "all current" not in out.out
    assert "1 of them could not be compared" in out.out


def test_check_text_does_not_call_a_withdrawn_dependency_current(monkeypatch, capsys):
    project = _project([Dependency(name="django", version="4.2.1")])
    code, out, _ = _run_check(
        monkeypatch,
        capsys,
        [project],
        [
            (
                200,
                {
                    "packages": [
                        _row(
                            "django",
                            "4.2.1",
                            versions_behind=0,
                            latest="4.2.1",
                            latest_stable="4.2.1",
                            installed_yanked=True,
                            installed_yanked_reason="Breaks on Python 3.13.",
                        )
                    ]
                },
            )
        ],
    )
    assert code == 0
    assert "all current" not in out.out
    assert "Withdrawn versions in this build:" in out.out
    assert "django 4.2.1  (yours)" in out.out
    assert "django is withdrawn with no newer release to move to." in out.out


def test_check_text_keeps_the_link_in_a_withdrawal_reason(monkeypatch, capsys):
    reason = "Please see https://eslint.org/version-support for other options."
    project = _project([Dependency(name="eslint", version="8.57.0")])
    code, out, _ = _run_check(
        monkeypatch,
        capsys,
        [project],
        [
            (
                200,
                {
                    "packages": [
                        _row(
                            "eslint",
                            "8.57.0",
                            versions_behind=0,
                            latest="8.57.0",
                            latest_stable="8.57.0",
                            installed_yanked=True,
                            installed_yanked_reason=reason,
                        )
                    ]
                },
            )
        ],
    )
    assert code == 0
    assert "https://eslint.org/version-support" in out.out
    assert reason in out.out


def test_check_text_lists_a_deprecated_version_under_its_own_heading(
    monkeypatch, capsys
):
    project = _project([Dependency(name="chalk", version="1.1.2")])
    code, out, _ = _run_check(
        monkeypatch,
        capsys,
        [project],
        [
            (
                200,
                {
                    "packages": [
                        _row(
                            "chalk",
                            "1.1.2",
                            versions_behind=0,
                            latest="1.1.2",
                            latest_stable="1.1.2",
                            installed_deprecated=True,
                            installed_deprecated_reason=(
                                "chalk@1.1.2 introduces breaking changes. "
                                "Please use 1.1.3 or above."
                            ),
                        )
                    ]
                },
            )
        ],
    )
    assert code == 0
    assert "Deprecated versions in this build:" in out.out
    assert "Withdrawn versions in this build:" not in out.out
    assert "chalk 1.1.2  (yours)" in out.out
    assert "Please use 1.1.3 or above." in out.out
    assert "all current" in out.out


def test_check_text_prints_withdrawals_before_deprecations(monkeypatch, capsys):
    project = _project(
        [
            Dependency(name="chalk", version="1.1.2"),
            Dependency(name="django", version="4.2.1"),
        ]
    )
    code, out, _ = _run_check(
        monkeypatch,
        capsys,
        [project],
        [
            (
                200,
                {
                    "packages": [
                        _row(
                            "chalk",
                            "1.1.2",
                            versions_behind=0,
                            installed_deprecated=True,
                            installed_deprecated_reason="Please use 1.1.3 or above.",
                        ),
                        _row(
                            "django",
                            "4.2.1",
                            versions_behind=0,
                            installed_yanked=True,
                            installed_yanked_reason="Breaks on Python 3.13.",
                        ),
                    ]
                },
            )
        ],
    )
    assert code == 0
    assert out.out.index("Withdrawn versions in this build:") < out.out.index(
        "Deprecated versions in this build:"
    )
    assert "django 4.2.1" in out.out.split("Deprecated versions")[0]
    assert "chalk 1.1.2" in out.out.split("Deprecated versions")[1]


def test_check_text_survives_a_server_that_does_not_know_deprecation(
    monkeypatch, capsys
):
    project = _project([Dependency(name="django", version="4.2.1")])
    row = _row("django", "4.2.1", versions_behind=0)
    del row["installed_deprecated"], row["installed_deprecated_reason"]
    code, out, _ = _run_check(
        monkeypatch, capsys, [project], [(200, {"packages": [row]})]
    )
    assert code == 0
    assert "Deprecated versions in this build:" not in out.out


def test_check_text_names_a_package_whose_version_could_not_be_placed(
    monkeypatch, capsys
):
    project = _project(
        [
            Dependency(name="django", version="4.2.12"),
            Dependency(name="sqlparse", version="0.4.0"),
        ]
    )
    code, out, _ = _run_check(
        monkeypatch,
        capsys,
        [project],
        [
            (
                200,
                {
                    "packages": [
                        _row(
                            "django",
                            "4.2.12",
                            installed_known=False,
                            versions_behind=None,
                        ),
                        _row("sqlparse", "0.4.0", versions_behind=0),
                    ]
                },
            )
        ],
    )
    assert code == 0
    assert "1 installed version is not one the registry published" in out.out
    assert "django  installed: 4.2.12" in out.out
    assert "1 of them could not be compared" in out.out


def test_check_text_stops_at_the_first_failure_as_it_always_did(monkeypatch, capsys):
    import httpx

    project = _project([Dependency(name="django", version="4.2.1")])
    code, out, _ = _run_check(
        monkeypatch,
        capsys,
        [project],
        [httpx.ConnectError("no route to host")],
    )
    assert code == 2
    assert out.out == ""
    assert out.err.startswith("error: could not reach https://pt.test")


def test_check_sends_names_and_versions_only(monkeypatch, capsys):
    project = _project([Dependency(name="django", version="4.2.1", parents=["x"])])
    _, _, client = _run_check(
        monkeypatch,
        capsys,
        [project],
        [(200, {"packages": [_row("django", "4.2.1")]})],
    )
    assert client.sent == [
        {"ecosystem": "pypi", "packages": [{"name": "django", "version": "4.2.1"}]}
    ]


def _under_cp1252(argv: list[str]):
    """Run `python argv...` the way a Windows pipe runs it, on any platform."""
    import os
    import subprocess

    env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
    return subprocess.run(
        [sys.executable, *argv], capture_output=True, env=env, timeout=60
    )


def test_a_real_command_writes_utf8_when_redirected(tmp_path):
    """Under cp1252 "…" used to leave as the single byte 0x85."""
    missing = tmp_path / "café…"
    result = _under_cp1252(
        ["-m", "packagetrackdev", "check", "--project", str(missing)]
    )
    assert result.returncode == 2
    assert "café…".encode() in result.stderr
    result.stderr.decode("utf-8")


def test_stdout_is_utf8_too_when_redirected():
    code = "; ".join(
        [
            "from packagetrackdev.__main__ import _utf8_output",
            "_utf8_output()",
            "print('clipped note…')",
        ]
    )
    result = _under_cp1252(["-c", code])
    assert result.stdout.strip() == "clipped note…".encode()


def test_push_over_a_name_of_another_ecosystem_prints_the_servers_reason(
    monkeypatch, capsys
):
    """The server refuses it and the CLI adds no rule of its own:
    it prints the server's sentence and exits 2, pushing nothing else."""
    import argparse
    from types import SimpleNamespace

    import packagetrackdev.__main__ as cli_main

    detail = (
        "Nothing was pushed. Project 'shop' holds pypi dependencies, and npm "
        "dependencies cannot replace them: that is another project, not an "
        "update. Push it under another name, such as 'shop-npm'."
    )
    client = _FakeClient(
        [(409, {"code": "ecosystem_conflict", "detail": detail, "project": "shop"})]
    )
    monkeypatch.setattr(cli_main.httpx, "Client", lambda **kwargs: client)
    npm = _project([], ecosystem="npm", source="package-lock.json")
    monkeypatch.setattr(cli_main, "_projects_or_exit", lambda folder, eco: [npm])
    monkeypatch.setattr(
        cli_main.config,
        "load",
        lambda **kwargs: SimpleNamespace(api_key="pkgt_x", server="https://pt.test"),
    )
    args = argparse.Namespace(
        api_key=None,
        server=None,
        project=Path("."),
        ecosystem=None,
        dry_run=False,
        name="shop",
    )
    capsys.readouterr()

    code = cli_main.cmd_push(args)

    captured = capsys.readouterr()
    assert code == 2
    assert captured.err.strip() == (
        f"error: https://pt.test answered HTTP 409: {detail}"
    )
    assert captured.out == ""
    assert len(client.sent) == 1


_ENCODED_FILES = [
    ("pypi", "requirements.txt", "flask==3.0.0\nrequests==2.31.0\n"),
    ("npm", "package.json", json.dumps({"dependencies": {"left-pad": "1.3.0"}})),
    (
        "npm",
        "package-lock.json",
        json.dumps(
            {
                "lockfileVersion": 3,
                "packages": {"": {}, "node_modules/ms": {"version": "2.1.3"}},
            }
        ),
    ),
    (
        "pypi",
        "uv.lock",
        'version = 1\n[[package]]\nname = "flask"\nversion = "3.0.0"\n'
        'source = { registry = "https://pypi.org/simple" }\n',
    ),
]


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "utf-16-le-bom"])
@pytest.mark.parametrize(("ecosystem", "filename", "text"), _ENCODED_FILES)
def test_a_marked_encoding_reads_like_plain_utf8(
    tmp_path: Path, ecosystem, filename, text, encoding
):
    from packagetrackdev.lockfiles import read

    plain = tmp_path / "plain"
    marked = tmp_path / "marked"
    plain.mkdir()
    marked.mkdir()
    (plain / filename).write_bytes(text.encode("utf-8"))
    if encoding == "utf-16-le-bom":
        raw = b"\xff\xfe" + text.replace("\n", "\r\n").encode("utf-16-le")
    else:
        raw = text.encode(encoding)
    (marked / filename).write_bytes(raw)

    expected = read(ecosystem, plain / filename)
    got = read(ecosystem, marked / filename)

    assert expected is not None and expected.dependencies
    assert got is not None
    assert [(d.name, d.version) for d in got.dependencies] == [
        (d.name, d.version) for d in expected.dependencies
    ]
    assert got.skipped == expected.skipped


def test_bytes_that_are_no_text_are_refused_not_raised(tmp_path: Path):
    from packagetrackdev.lockfiles import decode, read

    path = tmp_path / "requirements.txt"
    path.write_bytes(b"flask==3.0.0\n\xc3\x28\n")
    assert decode(path.read_bytes()) is None
    assert read("pypi", path) is None


def test_a_bom_in_text_does_not_hide_the_format():
    from packagetrackdev.lockfiles import detect, parse

    bom = chr(0xFEFF)
    lock = _ENCODED_FILES[2][2]
    assert detect(bom + lock) == ("npm", "package-lock.json")
    project = parse("pypi", "requirements.txt", bom + "flask==3.0.0\n")
    assert [d.name for d in project.dependencies] == ["flask"]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("a===1.0", [("a", "1.0")]),
        ("a === 1.0", [("a", "1.0")]),
        ("a[x]===1.0", [("a", "1.0")]),
        ('a===1.0 ; python_version<"3.13"', [("a", "1.0")]),
        ("a===foobar", [("a", "foobar")]),
        ("a==1.0", [("a", "1.0")]),
        ("a==1.0+local", [("a", "1.0+local")]),
        ("a==1.0,<2", [("a", "")]),
        ("a==1.0, !=1.1", [("a", "")]),
        ("a===1.0,<2", [("a", "")]),
        ("a==1.*", [("a", "")]),
        ("a==1.0.*", [("a", "")]),
        ("a====1.0", []),
        ("a== =1.0", []),
    ],
)
def test_a_pin_is_one_exact_clause(line, expected):
    from packagetrackdev.lockfiles import parse

    project = parse("pypi", "requirements.txt", line + "\n")
    assert [(d.name, d.version) for d in project.dependencies] == expected
    assert project.skipped == (0 if expected else 1)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("attrs==23.1.0 \\", ("attrs", "23.1.0")),
        ("attrs==23.1.0\\", ("attrs", "23.1.0")),
        ("a===1.0 \\", ("a", "1.0")),
        ('a==1.0 ; os_name=="nt" ' + chr(92), ("a", "1.0")),
        ("a==1.0,<2 \\", ("a", "")),
        ("a>=1 \\", ("a", "")),
    ],
)
def test_a_hash_continuation_is_not_part_of_the_requirement(line, expected):
    from packagetrackdev.lockfiles import detect, parse

    content = line + "\n    --hash=sha256:abc\n"
    project = parse("pypi", "requirements.txt", content)
    assert [(d.name, d.version) for d in project.dependencies] == [expected]
    assert project.skipped == 1
    assert detect(content) == ("pypi", "requirements.txt")


_NPM_WORKSPACES = {
    "name": "mono",
    "lockfileVersion": 3,
    "packages": {
        "": {
            "name": "mono",
            "workspaces": ["packages/*"],
            "devDependencies": {"typescript": "^5.0.0"},
        },
        "packages/app": {
            "name": "@mono/app",
            "version": "0.1.0",
            "dependencies": {"lodash": "^4.17.0", "@mono/lib": "*"},
        },
        "packages/lib": {
            "name": "@mono/lib",
            "version": "0.2.0",
            "dependencies": {"ms": "^2.1.0"},
        },
        "packages/tool": {"name": "tool", "dependencies": {"chalk": "^5.0.0"}},
        "node_modules/@mono/app": {"resolved": "packages/app", "link": True},
        "node_modules/@mono/lib": {"resolved": "packages/lib", "link": True},
        "node_modules/tool": {"resolved": "packages/tool", "link": True},
        "node_modules/typescript": {"version": "5.4.5", "dev": True},
        "node_modules/lodash": {"version": "4.17.21"},
        "node_modules/ms": {"version": "2.1.3"},
        "node_modules/chalk": {"version": "5.3.0", "dependencies": {"ansi": "^1"}},
        "node_modules/ansi": {"version": "1.0.0"},
    },
}


def test_npm_workspaces_are_the_project_not_its_dependencies(tmp_path: Path):
    (tmp_path / "package-lock.json").write_text(
        json.dumps(_NPM_WORKSPACES), encoding="utf-8"
    )
    project = read("npm", tmp_path / "package-lock.json")

    by_name = {d.name: d for d in project.dependencies}
    assert sorted(by_name) == ["ansi", "chalk", "lodash", "ms", "typescript"]
    for own in ("typescript", "lodash", "ms", "chalk"):
        assert by_name[own].parents == [], own
    assert by_name["ansi"].parents == ["chalk"]
    assert project.skipped == 3


def _npm_lock(tmp_path: Path, packages: dict):
    from packagetrackdev.lockfiles import read

    path = tmp_path / "package-lock.json"
    path.write_text(
        json.dumps({"lockfileVersion": 3, "packages": packages}), encoding="utf-8"
    )
    project = read("npm", path)
    return {(d.name, d.version): d.parents for d in project.dependencies}


def test_npm_a_nested_old_copy_names_the_package_that_pulled_it_in(tmp_path: Path):
    rows = _npm_lock(
        tmp_path,
        {
            "": {"dependencies": {"glob": "^10.0.0", "x": "^1.0.0"}},
            "node_modules/glob": {
                "version": "10.3.10",
                "dependencies": {"minimatch": "^9"},
            },
            "node_modules/minimatch": {"version": "9.0.3"},
            "node_modules/x": {"version": "1.0.0", "dependencies": {"glob": "^7"}},
            "node_modules/x/node_modules/glob": {
                "version": "7.0.0",
                "dependencies": {"inflight": "^1", "minimatch": "^3"},
            },
            "node_modules/x/node_modules/minimatch": {"version": "3.1.2"},
            "node_modules/inflight": {"version": "1.0.6"},
            "node_modules/y": {"version": "2.0.0", "dependencies": {"minimatch": "^9"}},
        },
    )
    assert rows[("glob", "10.3.10")] == []
    assert rows[("glob", "7.0.0")] == ["x"]
    assert rows[("minimatch", "9.0.3")] == ["glob", "y"]
    assert rows[("minimatch", "3.1.2")] == ["glob"]
    assert rows[("inflight", "1.0.6")] == ["glob"]


def test_npm_a_workspace_finds_its_own_nested_copy_first(tmp_path: Path):
    rows = _npm_lock(
        tmp_path,
        {
            "": {"workspaces": ["packages/*"], "dependencies": {"x": "^2"}},
            "packages/app": {"name": "app", "dependencies": {"x": "^1"}},
            "node_modules/app": {"resolved": "packages/app", "link": True},
            "node_modules/x": {"version": "2.0.0"},
            "packages/app/node_modules/x": {"version": "1.0.0"},
        },
    )
    assert rows == {("x", "2.0.0"): [], ("x", "1.0.0"): []}


def test_npm_one_version_in_two_places_is_one_row(tmp_path: Path):
    rows = _npm_lock(
        tmp_path,
        {
            "": {"dependencies": {"ms": "^2", "a": "^1", "b": "^1"}},
            "node_modules/ms": {"version": "2.1.3"},
            "node_modules/a": {"version": "1.0.0", "dependencies": {"ms": "^1"}},
            "node_modules/a/node_modules/ms": {"version": "1.0.0"},
            "node_modules/b": {"version": "1.0.0", "dependencies": {"ms": "^1"}},
            "node_modules/b/node_modules/ms": {"version": "1.0.0"},
        },
    )
    assert rows[("ms", "2.1.3")] == []
    assert rows[("ms", "1.0.0")] == ["a", "b"]


_CARGO_TWO_SYNS = """version = 3

[[package]]
name = "app"
version = "0.1.0"
dependencies = ["serde_derive", "syn 2.0.50", "log"]

[[package]]
name = "serde_derive"
version = "1.0.0"
source = "registry+https://github.com/rust-lang/crates.io-index"
dependencies = [
    "log",
    "syn 1.0.109 (registry+https://github.com/rust-lang/crates.io-index)",
]

[[package]]
name = "syn"
version = "1.0.109"
source = "registry+https://github.com/rust-lang/crates.io-index"
dependencies = ["unicode-ident"]

[[package]]
name = "syn"
version = "2.0.50"
source = "registry+https://github.com/rust-lang/crates.io-index"
dependencies = ["unicode-ident"]

[[package]]
name = "unicode-ident"
version = "1.0.12"
source = "registry+https://github.com/rust-lang/crates.io-index"

[[package]]
name = "log"
version = "0.4.20"
source = "registry+https://github.com/rust-lang/crates.io-index"
"""


def test_cargo_keeps_both_versions_of_a_crate():
    from packagetrackdev.lockfiles import parse

    project = parse("cargo", "Cargo.lock", _CARGO_TWO_SYNS)
    rows = {(d.name, d.version): d.parents for d in project.dependencies}
    assert rows == {
        ("log", "0.4.20"): [],  # the app's own, though serde_derive wants it too
        ("serde_derive", "1.0.0"): [],
        ("syn", "1.0.109"): ["serde_derive"],
        ("syn", "2.0.50"): [],
        ("unicode-ident", "1.0.12"): ["syn"],
    }
    assert project.skipped == 0


_UV_FORKED_NUMPY = """version = 1
requires-python = ">=3.9"

[[package]]
name = "app"
version = "0.1.0"
source = { virtual = "." }
dependencies = [
    { name = "numpy", version = "1.26.4", marker = "python_full_version < '3.10'" },
    { name = "numpy", version = "2.1.0", marker = "python_full_version >= '3.10'" },
    { name = "pandas" },
]

[[package]]
name = "numpy"
version = "1.26.4"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "numpy"
version = "2.1.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "pandas"
version = "2.2.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [
    { name = "numpy", version = "1.26.4", marker = "python_full_version < '3.10'" },
    { name = "numpy", version = "2.1.0", marker = "python_full_version >= '3.10'" },
    { name = "tzdata" },
]

[[package]]
name = "tzdata"
version = "2024.1"
source = { registry = "https://pypi.org/simple" }
"""


def test_uv_keeps_both_sides_of_a_marker_fork():
    from packagetrackdev.lockfiles import parse

    project = parse("pypi", "uv.lock", _UV_FORKED_NUMPY)
    rows = {(d.name, d.version): d.parents for d in project.dependencies}
    assert rows == {
        ("numpy", "1.26.4"): [],
        ("numpy", "2.1.0"): [],
        ("pandas", "2.2.0"): [],
        ("tzdata", "2024.1"): ["pandas"],
    }


def test_poetry_keeps_both_versions_of_a_name():
    from packagetrackdev.lockfiles import parse

    content = (
        '[[package]]\nname = "numpy"\nversion = "1.26.4"\n\n'
        '[[package]]\nname = "numpy"\nversion = "2.1.0"\n\n'
        '[[package]]\nname = "pandas"\nversion = "2.2.0"\n\n'
        '[package.dependencies]\nnumpy = ">=1.22"\n\n'
        '[metadata]\nlock-version = "2.0"\ncontent-hash = "abc"\n'
    )
    project = parse("pypi", "poetry.lock", content)
    rows = {(d.name, d.version): d.parents for d in project.dependencies}
    assert rows == {
        ("numpy", "1.26.4"): ["pandas"],
        ("numpy", "2.1.0"): ["pandas"],
        ("pandas", "2.2.0"): [],
    }
